import server
from aiohttp import web
import os
import json
import torch
import numpy as np
from PIL import Image
import urllib.parse
import io
from comfy.utils import common_upscale
import hashlib
import shutil
from send2trash import send2trash
import time
import cv2
import subprocess
import re
import base64
import asyncio
import fnmatch
import folder_paths
import logging

logger = logging.getLogger(__name__)

VAE_STRIDE = (4, 8, 8)
PATCH_SIZE = (1, 2, 2)

def validate_path(path):
    """Validate a file path, blocking directory traversal.
    Accepts both relative and absolute paths.
    Returns the normalized path, or None if the path is invalid/unsafe."""
    if not path:
        return None
    path = path.replace("\\", "/")
    if ".." in path.split("/"):
        return None
    return os.path.normpath(path)

NODE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(NODE_DIR, "config.json")
METADATA_FILE = os.path.join(NODE_DIR, "metadata.json")
UI_STATE_FILE = os.path.join(NODE_DIR, "lig_ui_state.json")
CACHE_DIR = os.path.join(NODE_DIR, ".cache")
THUMBNAIL_CACHE_DIR = os.path.join(CACHE_DIR, "thumbnails")

SUPPORTED_IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp']
SUPPORTED_VIDEO_EXTENSIONS = ['.mp4', '.webm', '.mov', '.mkv', '.avi']
SUPPORTED_AUDIO_EXTENSIONS = ['.mp3', '.wav', '.ogg', '.flac', '.m4a']

CACHE_LIFETIME = 1800
DIRSCAN_CACHE_DIR = os.path.join(CACHE_DIR, "dirscan")


class DirCache:
    def __init__(self, disk_dir, ttl=1800):
        self._mem = {}          # key -> (data, timestamp)
        self._disk_dir = disk_dir
        self._ttl = ttl
        self._locks = {}        # key -> asyncio.Lock
        os.makedirs(disk_dir, exist_ok=True)

    def _disk_path(self, key):
        h = hashlib.md5(key.encode()).hexdigest()
        return os.path.join(self._disk_dir, f"{h}.json")

    def get(self, key):
        now = time.time()
        # L1: memory
        if key in self._mem:
            data, ts = self._mem[key]
            if now - ts < self._ttl:
                return data
            del self._mem[key]
        # L2: disk
        dp = self._disk_path(key)
        try:
            with open(dp, 'r') as f:
                entry = json.load(f)
            if now - entry['ts'] < self._ttl:
                self._mem[key] = (entry['data'], entry['ts'])
                return entry['data']
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            pass
        return None

    def put(self, key, data):
        now = time.time()
        self._mem[key] = (data, now)
        dp = self._disk_path(key)
        try:
            with open(dp, 'w') as f:
                json.dump({'data': data, 'ts': now}, f)
        except Exception:
            pass

    def invalidate(self, key=None):
        if key is None:
            self._mem.clear()
            for fname in os.listdir(self._disk_dir):
                try:
                    os.remove(os.path.join(self._disk_dir, fname))
                except Exception:
                    pass
        else:
            self._mem.pop(key, None)
            try:
                os.remove(self._disk_path(key))
            except FileNotFoundError:
                pass

    def lock_for(self, key):
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]


dir_cache = DirCache(DIRSCAN_CACHE_DIR, ttl=CACHE_LIFETIME)


def ensure_cache_dirs():
    os.makedirs(THUMBNAIL_CACHE_DIR, exist_ok=True)

ensure_cache_dirs()

def save_config(data):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4)
    except Exception as e: print(f"LocalMediaManager: Error saving config: {e}")

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f: return json.load(f)
        except: pass
    return {}

METADATA_CACHE = {'data': None, 'mtime': 0}

def load_metadata():
    if not os.path.exists(METADATA_FILE): return {}
    try:
        file_mtime = os.path.getmtime(METADATA_FILE)
        if METADATA_CACHE['data'] is not None and file_mtime == METADATA_CACHE['mtime']:
            return METADATA_CACHE['data']
        with open(METADATA_FILE, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
            normalized = {k.replace("\\", "/"): v for k, v in metadata.items()}
            METADATA_CACHE['data'] = normalized
            METADATA_CACHE['mtime'] = file_mtime
            return normalized
    except: return {}

def save_metadata(data):
    try:
        with open(METADATA_FILE, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e: print(f"LocalMediaManager: Error saving metadata: {e}")
    METADATA_CACHE['data'] = None
    dir_cache.invalidate()

def load_ui_state():
    if not os.path.exists(UI_STATE_FILE): return {}
    try:
        with open(UI_STATE_FILE, 'r', encoding='utf-8') as f: return json.load(f)
    except: return {}

def save_ui_state(data):
    try:
        with open(UI_STATE_FILE, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4)
    except Exception as e: print(f"LocalMediaManager: Error saving UI state: {e}")

def extract_prompts(metadata):
    positive_prompts, negative_prompts = [], []

    if not metadata:
        return "", ""

    parameters = metadata.get('parameters')
    if isinstance(parameters, str):
        neg_prompt_match = re.search(r'Negative prompt:\s*(.*)', parameters, re.DOTALL)
        if neg_prompt_match:
            negative = neg_prompt_match.group(1).split('Steps:')[0].strip()
            positive = parameters.split('Negative prompt:')[0].strip()
            return positive.strip(), negative.strip()
        else:
            return parameters.split('Steps:')[0].strip(), ""

    workflow_str = metadata.get('workflow') or metadata.get('prompt')
    if not isinstance(workflow_str, str):
        return (str(metadata.get('prompt', '')), "")

    try:
        workflow = json.loads(workflow_str)
        if 'nodes' not in workflow or not isinstance(workflow.get('nodes'), list):
            return str(workflow), ""

        nodes_by_id = {str(n['id']): n for n in workflow['nodes']}
        all_links = workflow.get('links', [])

        def find_ground_truth_from_source(origin_node_id, origin_slot_index):
            display_keywords = ['show', 'text', 'preview', 'any']
            for link in all_links:
                if str(link[1]) == str(origin_node_id) and link[2] == origin_slot_index:
                    target_node = nodes_by_id.get(str(link[3]))
                    if not target_node: continue

                    node_type = target_node.get('type', '').lower()
                    prop_name = target_node.get('properties', {}).get('Node name for S&R', '').lower()
                    if any(k in node_type or k in prop_name for k in display_keywords):
                        val = target_node.get('widgets_values', [[""]])[0]
                        return val[0] if isinstance(val, list) else val
            return None

        def resolve_text_fallback(node):
            if not any('link' in i for i in node.get('inputs', []) if i.get('type') == 'STRING'):
                widgets = node.get('widgets_values', [])
                return next((w for w in widgets if isinstance(w, str)), "")

            combined_text = ""
            for inp in node.get('inputs', []):
                if inp.get('type') == 'STRING' and 'link' in inp:
                    link_info = next((l for l in all_links if str(l[0]) == str(inp['link'])), None)
                    if link_info:
                        combined_text += resolve_text_fallback(nodes_by_id[str(link_info[1])])
            return combined_text

        def is_sampler(node):
            return 'Sampler' in node.get('type', '')

        def check_downstream_for_sampler(start_node, visited=None):
            if visited is None: visited = set()
            start_node_id = str(start_node['id'])
            if start_node_id in visited: return False
            visited.add(start_node_id)

            if is_sampler(start_node):
                return True

            for output in start_node.get('outputs', []):
                for link_id in output.get('links', []):
                    link_info = next((l for l in all_links if str(l[0]) == str(link_id)), None)
                    if link_info:
                        target_node = nodes_by_id.get(str(link_info[3]))
                        if target_node and check_downstream_for_sampler(target_node, visited):
                            return True
            return False

        for node in workflow['nodes']:
            if 'CLIPTextEncode' in node.get('type', ''):
                if check_downstream_for_sampler(node):
                    text_input = next((i for i in node.get('inputs', []) if i.get('name') == 'text'), None)
                    prompt_text = ""
                    if text_input and 'link' in text_input:
                        link_info = next((l for l in all_links if str(l[0]) == str(text_input['link'])), None)
                        if link_info:
                            origin_id, origin_slot = str(link_info[1]), link_info[2]
                            prompt_text = find_ground_truth_from_source(origin_id, origin_slot)
                            if prompt_text is None:
                                prompt_text = resolve_text_fallback(nodes_by_id[origin_id])
                    else:
                        prompt_text = (node.get('widgets_values') or [""])[0]

                    if 'negative' in node.get('title', '').lower():
                        negative_prompts.append(prompt_text)
                    else:
                        positive_prompts.append(prompt_text)

            elif 'CivitaiGalleryNode' in node.get('type', ''):
                properties = node.get('properties', {})
                if 'selection_data' in properties:
                    try:
                        selection_data = json.loads(properties['selection_data'])
                        meta = selection_data.get('item', {}).get('meta', {})
                        if 'prompt' in meta:
                            positive_prompts.append(meta['prompt'])
                        if 'negativePrompt' in meta:
                            negative_prompts.append(meta['negativePrompt'])
                    except (json.JSONDecodeError, AttributeError):
                        pass

        return " ".join(positive_prompts).strip(), " ".join(negative_prompts).strip()

    except Exception as e:
        print(f"LMM Error: Failed to parse workflow. Error: {e}")
        return "", ""

class LocalMediaManagerNode:
    @classmethod
    def IS_CHANGED(cls, selection, current_path="", **kwargs):
        m = hashlib.sha256()
        m.update(str(selection).encode())
        m.update(str(current_path).encode())

        try:
            selections_list = json.loads(selection)
            input_dir = folder_paths.get_input_directory()

            for item in selections_list:
                path = item.get('path')
                if path and os.path.exists(path):
                    mtime = os.path.getmtime(path)
                    m.update(str(mtime).encode())

                    filename = os.path.basename(path)
                    name, _ = os.path.splitext(filename)
                    mask_filename = f"{name}_mask.png"

                    input_mask_path = os.path.join(input_dir, mask_filename)
                    if os.path.exists(input_mask_path):
                        mask_mtime = os.path.getmtime(input_mask_path)
                        m.update(str(mask_mtime).encode())
                        m.update(str(input_mask_path).encode())

                    original_mask_path = os.path.join(os.path.dirname(path), mask_filename)
                    if os.path.exists(original_mask_path):
                        mask_mtime = os.path.getmtime(original_mask_path)
                        m.update(str(mask_mtime).encode())
                        m.update(str(original_mask_path).encode())

        except Exception:
            pass

        return m.hexdigest()

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {},
            "hidden": {
                "unique_id": "UNIQUE_ID",
                "selection": ("STRING", {"default": "[]", "multiline": True, "forceInput": True}),
                "gallery_unique_id_widget": ("STRING", {"default": "", "multiline": False}),
                "current_path": ("STRING", {"default": "", "multiline": False}),
            },
        }

    RETURN_TYPES = ("IMAGE", "MASK", "LMM_ALL_PATHS", "STRING", "STRING",)
    RETURN_NAMES = ("image", "mask", "paths", "path", "info",)
    FUNCTION = "get_selected_media"
    CATEGORY = "📜Asset Gallery/Local"

    def get_selected_media(self, unique_id, gallery_unique_id_widget="", selection="[]", current_path=""):
        try:
            selections_list = json.loads(selection)
        except (json.JSONDecodeError, TypeError):
            selections_list = []

        image_paths = [item['path'] for item in selections_list if item.get('type') == 'image' and 'path' in item]

        final_image_tensor = torch.zeros(1, 1, 1, 3)
        info_strings = []
        valid_image_paths = []
        enriched_selection_list = []

        if image_paths:
            sizes = {}
            batch_has_alpha = False

            for media_path in image_paths:
                if os.path.exists(media_path):
                    try:
                        with Image.open(media_path) as img:
                            sizes[img.size] = sizes.get(img.size, 0) + 1
                            valid_image_paths.append(media_path)
                            if not batch_has_alpha and (img.mode == 'RGBA' or (img.mode == 'P' and 'transparency' in img.info)):
                                batch_has_alpha = True
                    except Exception as e:
                        print(f"LMM: Error reading size for {media_path}: {e}")

            if valid_image_paths:
                dominant_size = max(sizes.items(), key=lambda x: x[1])[0]
                target_width, target_height = dominant_size

                target_mode = "RGBA" if batch_has_alpha else "RGB"
                image_tensors = []

                for media_path in valid_image_paths:
                    try:
                        with Image.open(media_path) as img:
                            img_out = img.convert(target_mode)

                            if img.size[0] != target_width or img.size[1] != target_height:
                                img_array_pre = np.array(img_out).astype(np.float32) / 255.0
                                tensor_pre = torch.from_numpy(img_array_pre)[None,].permute(0, 3, 1, 2)
                                tensor_post = common_upscale(tensor_pre, target_width, target_height, "lanczos", "center")
                                img_array = tensor_post.permute(0, 2, 3, 1).cpu().numpy().squeeze(0)
                            else:
                                img_array = np.array(img_out).astype(np.float32) / 255.0

                            image_tensor = torch.from_numpy(img_array)[None,]
                            image_tensors.append(image_tensor)

                            full_info = {"filename": os.path.basename(media_path), "width": img.width, "height": img.height, "mode": img.mode, "format": img.format}
                            metadata = {}
                            if 'parameters' in img.info: metadata['parameters'] = img.info['parameters']
                            if 'prompt' in img.info: metadata['prompt'] = img.info['prompt']
                            if 'workflow' in img.info: metadata['workflow'] = img.info['workflow']
                            if metadata: full_info['metadata'] = metadata
                            info_strings.append(json.dumps(full_info, ensure_ascii=False))
                    except Exception as e:
                        print(f"LMM: Error processing image {media_path}: {e}")

                if image_tensors:
                    final_image_tensor = torch.cat(image_tensors, dim=0)
                    if final_image_tensor.shape[-1] == 4:
                        if torch.min(final_image_tensor[:, :, :, 3]) > 0.9999:
                            final_image_tensor = final_image_tensor[:, :, :, :3]

        mask_tensor = None
        if final_image_tensor is not None and final_image_tensor.nelement() > 0:
            h, w = final_image_tensor.shape[1], final_image_tensor.shape[2]

            if valid_image_paths and final_image_tensor.shape[0] == 1:
                first_image_path = valid_image_paths[0]

                filename = os.path.basename(first_image_path)
                name, _ = os.path.splitext(filename)
                input_dir = folder_paths.get_input_directory()

                input_mask_path = os.path.join(input_dir, f"{name}_mask.png")

                original_dir_mask_path = os.path.join(os.path.dirname(first_image_path), f"{name}_mask.png")

                mask_file_to_load = None
                if os.path.exists(input_mask_path):
                    mask_file_to_load = input_mask_path
                elif os.path.exists(original_dir_mask_path):
                    mask_file_to_load = original_dir_mask_path

                if mask_file_to_load:
                    try:
                        with Image.open(mask_file_to_load) as mask_img:
                            if mask_img.width != w or mask_img.height != h:
                                mask_img = mask_img.resize((w, h), Image.NEAREST)

                            if 'A' in mask_img.getbands():
                                mask_data = mask_img.split()[-1]
                            else:
                                mask_data = mask_img.convert("L")

                            mask_np = np.array(mask_data).astype(np.float32) / 255.0
                            mask_tensor = torch.from_numpy(mask_np).unsqueeze(0)

                    except Exception as e:
                        print(f"LMM: Error loading mask file: {e}")

                if mask_tensor is None:
                    try:
                        with Image.open(first_image_path) as img:
                            if img.mode == 'RGBA':
                                alpha = np.array(img.split()[-1]).astype(np.float32) / 255.0
                                inverted_alpha = 1.0 - alpha
                                mask_tensor = torch.from_numpy(inverted_alpha).unsqueeze(0)
                    except: pass

            if mask_tensor is None:
                 mask_tensor = torch.zeros(final_image_tensor.shape[0], h, w, dtype=torch.float32)

        if final_image_tensor.nelement() == 0:
             final_image_tensor = torch.zeros(1, 64, 64, 3)
             mask_tensor = torch.zeros(1, 64, 64)
        elif mask_tensor is None:
             mask_tensor = torch.zeros(final_image_tensor.shape[0], final_image_tensor.shape[1], final_image_tensor.shape[2], dtype=torch.float32)

        for item in selections_list:
            enriched_item = item.copy()
            if item.get('type') == 'image' and 'path' in item and os.path.exists(item['path']):
                try:
                    with Image.open(item['path']) as img:
                        metadata_payload = {}
                        if 'parameters' in img.info: metadata_payload['parameters'] = img.info['parameters']
                        if 'prompt' in img.info: metadata_payload['prompt'] = img.info['prompt']
                        if 'workflow' in img.info: metadata_payload['workflow'] = img.info['workflow']
                        enriched_item['metadata'] = metadata_payload
                except Exception:
                    enriched_item['metadata'] = {}
            enriched_selection_list.append(enriched_item)

        info_string_out = json.dumps(info_strings, indent=4, ensure_ascii=False)
        if len(info_strings) == 1:
            try:
                single_info = json.loads(info_strings[0])
                workflow_data_str = single_info.get("metadata", {}).get("workflow")
                if workflow_data_str:
                    try:
                        workflow_json = json.loads(workflow_data_str)
                        info_string_out = json.dumps(workflow_json, indent=4, ensure_ascii=False)
                    except:
                        info_string_out = workflow_data_str
            except Exception as e:
                print(f"LMM: Could not parse workflow info, falling back to default. Error: {e}")
                pass

        full_selection_json_string = json.dumps(enriched_selection_list, ensure_ascii=False)

        single_path_out = ""

        if len(selections_list) == 1:
            item = selections_list[0]
            if 'path' in item and os.path.exists(item['path']):
                single_path_out = item['path']

        elif len(selections_list) == 0:
            if current_path and os.path.isdir(current_path):
                single_path_out = current_path
            else:
                try:
                    ui_states = load_ui_state()
                    node_key = f"{gallery_unique_id_widget}_{unique_id}" if gallery_unique_id_widget else None
                    if node_key and node_key in ui_states:
                        saved_path = ui_states[node_key].get("last_path", "")
                        if saved_path and os.path.isdir(saved_path):
                            single_path_out = saved_path
                except Exception:
                    pass

        return (final_image_tensor, mask_tensor, full_selection_json_string, single_path_out, info_string_out,)

def parse_selection_and_get_item(selection_json_str: str, index: int, expected_type: str = None):
    try:
        selection_list = json.loads(selection_json_str)
        if not isinstance(selection_list, list) or not (0 <= index < len(selection_list)):
            return None

        item = selection_list[index]
        if expected_type is None or item.get("type") == expected_type:
            return item
        else:
            return None
    except (json.JSONDecodeError, TypeError):
        return None

def target_size(width, height, custom_width, custom_height):
    if custom_width == 0 and custom_height == 0:
        pass
    elif custom_height == 0 and width != 0:
        height = int(height * (custom_width / width))
        width = custom_width
    elif custom_width == 0 and height != 0:
        width = int(width * (custom_height / height))
        height = custom_height
    else:
        width = custom_width
        height = custom_height

    downscale_ratio = 8
    width = int(width / downscale_ratio + 0.5) * downscale_ratio
    height = int(height / downscale_ratio + 0.5) * downscale_ratio
    return (width, height)

def get_audio(file_path, start_time=0, duration=0):
    args = ['ffmpeg', "-i", file_path, "-vn"]
    if start_time > 0:
        args += ["-ss", str(start_time)]
    if duration > 0:
        args += ["-t", str(duration)]

    args += ["-f", "f32le", "-acodec", "pcm_f32le", "-ar", "44100", "-ac", "2", "-"]

    try:
        proc = subprocess.run(args, capture_output=True, check=True)

        info_str = proc.stderr.decode('utf-8', 'replace')

        sample_rate = 44100
        channels = 2

        sr_match = re.search(r'(\d+)\s+Hz', info_str)
        if sr_match:
            sample_rate = int(sr_match.group(1))

        ch_match = re.search(r'Hz,\s+(mono|stereo)', info_str)
        if ch_match:
            channels = 1 if ch_match.group(1) == 'mono' else 2

        waveform = torch.from_numpy(np.frombuffer(proc.stdout, dtype=np.float32))
        waveform = waveform.reshape(-1, channels).permute(1, 0)

        return {'waveform': waveform.unsqueeze(0), 'sample_rate': sample_rate}

    except subprocess.CalledProcessError as e:
        print(f"LMM Selector: Could not extract audio from {file_path}. It might not contain an audio track. Error: {e.stderr.decode('utf-8', 'replace')}")
        return {'waveform': torch.zeros(1, 2, 1), 'sample_rate': 44100}
    except Exception as e:
        print(f"LMM Selector: An unexpected error occurred during audio extraction: {e}")
        return {'waveform': torch.zeros(1, 2, 1), 'sample_rate': 44100}

def cv_frame_generator(video_path, force_rate, frame_load_cap, skip_first_frames, select_every_nth):
    video_cap = cv2.VideoCapture(video_path)
    if not video_cap.isOpened():
        raise IOError(f"Cannot open video file: {video_path}")

    fps = video_cap.get(cv2.CAP_PROP_FPS)
    width = int(video_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(video_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(video_cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps if fps > 0 else 0

    yield {"width": width, "height": height, "fps": fps, "total_frames": total_frames, "duration": duration}

    base_frame_time = 1.0 / fps if fps > 0 else 0
    target_frame_time = 1.0 / force_rate if force_rate > 0 else base_frame_time
    if target_frame_time <= 0:
        target_frame_time = base_frame_time if base_frame_time > 0 else 1.0/30.0

    video_cap.set(cv2.CAP_PROP_POS_FRAMES, skip_first_frames)

    time_offset = target_frame_time
    frames_yielded = 0
    total_frames_evaluated = -1

    while video_cap.isOpened():
        current_pos_frames = skip_first_frames + frames_yielded
        if total_frames > 0 and current_pos_frames >= total_frames:
            break

        if force_rate > 0:
            while time_offset < target_frame_time:
                if not video_cap.grab():
                    video_cap.release()
                    return
                time_offset += base_frame_time
            time_offset -= target_frame_time
            ret, frame = video_cap.retrieve()
        else:
             ret, frame = video_cap.read()

        if not ret:
            break

        total_frames_evaluated += 1
        if total_frames_evaluated % select_every_nth != 0:
            continue

        yield cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        frames_yielded += 1
        if frame_load_cap > 0 and frames_yielded >= frame_load_cap:
            break

    video_cap.release()

class SelectOriginalImageNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "paths": ("LMM_ALL_PATHS", {"forceInput": True}),
                "index": ("INT", {"default": 0, "min": 0, "step": 1}),
                "frame_load_cap": ("INT", {"default": 1, "min": 1, "max": 4096, "step": 1, "tooltip": "Copy a single image into a specified number of image sequences"}),
                "generation_width": ("INT", {"default": 1024, "min": 64, "max": 8096, "step": 8, "tooltip": "The desired image width"}),
                "generation_height": ("INT", {"default": 1024, "min": 64, "max": 8096, "step": 8, "tooltip": "The desired image height"}),
                "aspect_ratio_preservation": (["original", "keep_input", "stretch_to_new", "crop_to_new"], {"tooltip": "Zoom Mode：\n- keep_input: Maintain the aspect ratio of the original image\n- stretch_to_new: Stretch to fit the new size\n- crop_to_new: Cropped to fit new sizes\n- original: No processing is performed, use the original image size"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "INT", "INT", "STRING", "STRING",)
    RETURN_NAMES = ("image", "width", "height", "positive_prompt", "negative_prompt",)
    FUNCTION = "get_original_image"
    CATEGORY = "📜Asset Gallery/Local"

    def get_original_image(self, paths, index, frame_load_cap, generation_width, generation_height, aspect_ratio_preservation):
        selected_item = parse_selection_and_get_item(paths, index, "image")

        empty_return = (torch.zeros(1, 1, 1, 3), 0, 0, "", "")

        if not selected_item or 'path' not in selected_item or not os.path.exists(selected_item['path']):
            return empty_return

        selected_path = selected_item['path']

        try:
            with Image.open(selected_path) as img:
                H_orig, W_orig = img.height, img.width

                img_out = img.convert("RGBA") if 'A' in img.getbands() else img.convert("RGB")
                img_array = np.array(img_out).astype(np.float32) / 255.0
                image_tensor = torch.from_numpy(img_array)[None,]

                if aspect_ratio_preservation != "original":
                    max_area = generation_width * generation_height
                    crop = "disabled"

                    if aspect_ratio_preservation == "keep_input":
                        aspect_ratio = H_orig / W_orig if W_orig > 0 else 1.0
                    elif aspect_ratio_preservation == "stretch_to_new" or aspect_ratio_preservation == "crop_to_new":
                        aspect_ratio = generation_height / generation_width if generation_width > 0 else 1.0
                        if aspect_ratio_preservation == "crop_to_new":
                            crop = "center"

                    lat_h = round(np.sqrt(max_area * aspect_ratio) / VAE_STRIDE[1] / PATCH_SIZE[1]) * PATCH_SIZE[1]
                    lat_w = round(np.sqrt(max_area / aspect_ratio) / VAE_STRIDE[2] / PATCH_SIZE[2]) * PATCH_SIZE[2]
                    h_new = int(lat_h * VAE_STRIDE[1])
                    w_new = int(lat_w * VAE_STRIDE[2])

                    processed_image = common_upscale(image_tensor.movedim(-1, 1), w_new, h_new, "lanczos", crop).movedim(1, -1)
                else:
                    w_new = W_orig
                    h_new = H_orig
                    processed_image = image_tensor

                if frame_load_cap > 1:
                    image_sequence = processed_image.repeat(frame_load_cap, 1, 1, 1)
                else:
                    image_sequence = processed_image

                metadata = selected_item.get('metadata', {})
                positive_prompt, negative_prompt = extract_prompts(metadata)

                return (image_sequence, w_new, h_new, positive_prompt, negative_prompt,)
        except Exception as e:
            print(f"LMM Selector: Error loading or processing image {selected_path}: {e}")
            return empty_return

class SelectOriginalVideoNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "paths": ("LMM_ALL_PATHS", {"forceInput": True}),
                "index": ("INT", {"default": 0, "min": 0, "step": 1}),
                "generation_width": ("INT", {"default": 1024, "min": 64, "max": 8096, "step": 8, "tooltip": "Expected video width to generate"}),
                "generation_height": ("INT", {"default": 1024, "min": 64, "max": 8096, "step": 8, "tooltip": "Expected video height"}),
                "aspect_ratio_preservation": (["original", "keep_input", "stretch_to_new", "crop_to_new"], {"tooltip": "Zoom Mode：\n- keep_input: Maintain the aspect ratio of the original video\n- stretch_to_new: Stretch to fit the new size\n- crop_to_new: Cropped to fit new sizes\n- original: No processing is performed, use the original video size"}),
                "force_rate": ("FLOAT", {"default": 0, "min": 0, "max": 240, "step": 1}),
                "frame_load_cap": ("INT", {"default": 0, "min": 0, "step": 1}),
                "skip_first_frames": ("INT", {"default": 0, "min": 0, "step": 1}),
                "select_every_nth": ("INT", {"default": 1, "min": 1, "step": 1}),
            },
        }

    RETURN_TYPES = ("IMAGE", "INT", "INT", "INT", "FLOAT", "AUDIO", "STRING",)
    RETURN_NAMES = ("IMAGE", "frame_count", "width", "height", "fps", "audio", "video_info",)
    FUNCTION = "get_original_video"
    CATEGORY = "📜Asset Gallery/Local"

    def get_original_video(self, paths, index, generation_width, generation_height, aspect_ratio_preservation, force_rate, frame_load_cap, skip_first_frames, select_every_nth):
        selected_item = parse_selection_and_get_item(paths, index, "video")

        empty_audio = {'waveform': torch.zeros(1, 2, 1), 'sample_rate': 44100}
        empty_return = (torch.zeros(1, 1, 1, 3), 0, 0, 0, 0.0, empty_audio, "{}")

        if not selected_item or 'path' not in selected_item or not os.path.exists(selected_item['path']):
            return empty_return

        selected_path = selected_item['path']

        audio_fps_estimate = force_rate if force_rate > 0 else 30
        audio_data = get_audio(selected_path, start_time=skip_first_frames / audio_fps_estimate)
        try:
            frame_generator = cv_frame_generator(selected_path, force_rate, frame_load_cap, skip_first_frames, select_every_nth)
            source_info = next(frame_generator)

            H_orig = source_info.get("height", 0)
            W_orig = source_info.get("width", 0)
            video_fps = source_info.get("fps", 0.0)

            should_resize = True
            crop = "disabled"

            if aspect_ratio_preservation != "original":
                max_area = generation_width * generation_height
                if aspect_ratio_preservation == "keep_input":
                    aspect_ratio = H_orig / W_orig if W_orig > 0 else 1.0
                else:
                    aspect_ratio = generation_height / generation_width if generation_width > 0 else 1.0
                    if aspect_ratio_preservation == "crop_to_new":
                        crop = "center"

                lat_h = round(np.sqrt(max_area * aspect_ratio) / VAE_STRIDE[1] / PATCH_SIZE[1]) * PATCH_SIZE[1]
                lat_w = round(np.sqrt(max_area / aspect_ratio) / VAE_STRIDE[2] / PATCH_SIZE[2]) * PATCH_SIZE[2]
                output_h = int(lat_h * VAE_STRIDE[1])
                output_w = int(lat_w * VAE_STRIDE[2])
            else:
                output_h = H_orig
                output_w = W_orig
                should_resize = False

            output_fps = force_rate if force_rate > 0 else video_fps
            frames = list(frame_generator)

            if not frames:
                return (torch.zeros(1, 1, 1, 3), 0, output_w, output_h, output_fps, audio_data, json.dumps(source_info))

            processed_frames = []
            for frame in frames:
                tensor_frame = torch.from_numpy(frame).float() / 255.0
                tensor_frame = tensor_frame.unsqueeze(0)

                if should_resize:
                    resized_frame = common_upscale(tensor_frame.movedim(-1, 1), output_w, output_h, "lanczos", crop).movedim(1, -1)
                else:
                    resized_frame = tensor_frame

                processed_frames.append(resized_frame.squeeze(0))

            final_tensor = torch.stack(processed_frames)
            return (final_tensor, final_tensor.shape[0], output_w, output_h, output_fps, audio_data, json.dumps(source_info, indent=4))
        except Exception as e:
            print(f"LMM Selector: Error loading or resizing video frames from {selected_path}: {e}")
            return empty_return

class SelectOriginalAudioNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "paths": ("LMM_ALL_PATHS", {"forceInput": True}),
                "index": ("INT", {"default": 0, "min": 0, "step": 1}),
                "seek_seconds": ("FLOAT", {"default": 0, "min": 0, "max": 100000, "step": 0.01}),
                "duration": ("FLOAT", {"default": 0, "min": 0, "max": 100000, "step": 0.01}),
            },
        }

    RETURN_TYPES = ("AUDIO", "FLOAT",)
    RETURN_NAMES = ("audio", "duration",)
    FUNCTION = "get_original_audio"
    CATEGORY = "📜Asset Gallery/Local"

    def get_original_audio(self, paths, index, seek_seconds, duration):
        selected_item = parse_selection_and_get_item(paths, index, "audio")

        if not selected_item or 'path' not in selected_item:
            return (None, 0.0)

        selected_path = selected_item['path']

        audio_data = get_audio(selected_path, start_time=seek_seconds, duration=duration)

        if audio_data and 'waveform' in audio_data and audio_data['waveform'] is not None:
            waveform = audio_data['waveform']
            sample_rate = audio_data['sample_rate']
            loaded_duration = waveform.shape[-1] / sample_rate
            return (audio_data, loaded_duration)
        else:
            return (None, 0.0)

prompt_server = server.PromptServer.instance

@prompt_server.routes.post("/local_image_gallery/update_metadata")
async def update_metadata(request):
    try:
        data = await request.json()
        path = validate_path(data.get("path", ""))
        rating, tags = data.get("rating"), data.get("tags")
        if not path: return web.json_response({"status": "error", "message": "Invalid path."}, status=400)


        metadata = load_metadata()

        if path not in metadata:
            metadata[path] = {}

        if rating is not None:
            metadata[path]['rating'] = int(rating)
        if tags is not None:
            metadata[path]['tags'] = [str(tag).strip() for tag in tags if str(tag).strip()]

        entry = metadata.get(path, {})
        rating_is_zero_or_missing = entry.get('rating', 0) == 0
        tags_are_empty_or_missing = not entry.get('tags')

        if rating_is_zero_or_missing and tags_are_empty_or_missing:
            del metadata[path]

        save_metadata(metadata)
        return web.json_response({"status": "ok", "message": "Metadata updated"})
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=500)

@prompt_server.routes.get("/local_image_gallery/get_saved_paths")
async def get_saved_paths(request):
    config = load_config()
    return web.json_response({"saved_paths": config.get("saved_paths", [])})

@prompt_server.routes.post("/local_image_gallery/save_paths")
async def save_paths(request):
    try:
        data = await request.json()
        paths = data.get("paths", [])
        config = load_config()
        config["saved_paths"] = paths
        save_config(config)
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=500)

@prompt_server.routes.get("/local_image_gallery/get_all_tags")
async def get_all_tags(request):
    try:
        metadata = load_metadata()
        all_tags = set()
        for item_meta in metadata.values():
            tags = item_meta.get("tags")
            if isinstance(tags, list):
                for tag in tags:
                    all_tags.add(tag)

        sorted_tags = sorted(list(all_tags), key=lambda s: s.lower())
        return web.json_response({"tags": sorted_tags})
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=500)

_IMAGE_EXTS = set(SUPPORTED_IMAGE_EXTENSIONS)
_VIDEO_EXTS = set(SUPPORTED_VIDEO_EXTENSIONS)
_AUDIO_EXTS = set(SUPPORTED_AUDIO_EXTENSIONS)

def _ext_to_type(ext):
    """Map a lowercase extension to 'image', 'video', 'audio', or None."""
    if ext in _IMAGE_EXTS:
        return 'image'
    if ext in _VIDEO_EXTS:
        return 'video'
    if ext in _AUDIO_EXTS:
        return 'audio'
    return None

def _video_has_workflow(filepath):
    """Check if a video file has embedded workflow data in the first 4MB."""
    try:
        with open(filepath, 'rb') as f:
            chunk = f.read(4 * 1024 * 1024)
            return b'"workflow":' in chunk or b'"prompt":' in chunk
    except Exception:
        return False

_workflow_cache = {}

def _check_has_workflow(filepath, mtime, item_type):
    """Cached workflow check for images and videos. Returns bool or None for audio/dirs."""
    if item_type == 'image':
        key = (filepath, mtime)
        cached = _workflow_cache.get(key)
        if cached is not None:
            return cached
        has_wf = False
        try:
            with Image.open(filepath) as img:
                if img.info and ('workflow' in img.info or 'prompt' in img.info):
                    has_wf = True
        except Exception:
            pass
        _workflow_cache[key] = has_wf
        return has_wf
    if item_type == 'video':
        key = (filepath, mtime)
        cached = _workflow_cache.get(key)
        if cached is not None:
            return cached
        has_wf = _video_has_workflow(filepath)
        _workflow_cache[key] = has_wf
        return has_wf
    return None

def _build_item(full_path, fname, stats, item_type, meta=None, metadata_store=None):
    """Build a media item dict. Provide either meta= directly or metadata_store= to look up by path."""
    if meta is None:
        meta = (metadata_store or {}).get(full_path, {})
    item = {
        'path': full_path,
        'name': fname,
        'mtime': stats.st_mtime,
        'rating': meta.get('rating', 0),
        'tags': meta.get('tags', []),
        'type': item_type,
    }
    has_wf = _check_has_workflow(full_path, stats.st_mtime, item_type)
    if has_wf is not None:
        item['has_workflow'] = has_wf
    return item

def _scan_directory(directory):
    """Pure computation: scan a single directory for media files. No caching."""
    if not directory or not os.path.isdir(directory):
        return None

    all_items = []
    metadata = load_metadata()

    for item in os.listdir(directory):
        raw_full_path = os.path.join(directory, item)
        full_path = raw_full_path.replace("\\", "/")
        try:
            stats = os.stat(raw_full_path)
            if os.path.isdir(full_path):
                all_items.append(_build_item(full_path, item, stats, 'dir', metadata_store=metadata))
            else:
                ext = os.path.splitext(item)[1].lower()
                item_type = _ext_to_type(ext)
                if item_type:
                    all_items.append(_build_item(full_path, item, stats, item_type, metadata_store=metadata))
        except (PermissionError, FileNotFoundError):
            continue

    return all_items


async def get_directory_data(directory, force_refresh=False):
    """Cached async wrapper around _scan_directory with per-key coalescing."""
    cache_key = directory
    if not force_refresh:
        cached = dir_cache.get(cache_key)
        if cached is not None:
            return cached
    async with dir_cache.lock_for(cache_key):
        if not force_refresh:
            cached = dir_cache.get(cache_key)
            if cached is not None:
                return cached
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _scan_directory, directory)
        if result is not None:
            dir_cache.put(cache_key, result)
        return result

def matches_query(query_lower, name_lower):
    """Match query against name. Supports substring and wildcards (* ?)."""
    if '*' in query_lower or '?' in query_lower:
        return fnmatch.fnmatch(name_lower, query_lower)
    return query_lower in name_lower

def levenshtein_distance(a, b):
    """Minimum single-char edits (insert, delete, substitute) to transform a into b."""
    if len(a) < len(b):
        return levenshtein_distance(b, a)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (ca != cb)))
        prev = curr
    return prev[-1]


def fuzzy_match(query_lower, name_lower):
    """Levenshtein fuzzy match against filename stem. Auto threshold: 1 for 3-5 chars, 2 for 6+."""
    qlen = len(query_lower)
    if qlen <= 2:
        return False
    max_dist = 1 if qlen <= 5 else 2
    stem = name_lower.rsplit('.', 1)[0] if '.' in name_lower else name_lower
    return levenshtein_distance(query_lower, stem) <= max_dist

def _search_walk(roots, query_lower, metadata, all_extensions, visited, match_fn):
    """Walk roots and collect matching files and directories."""
    all_items = []
    for root_dir in roots:
        if not root_dir or not os.path.isdir(root_dir):
            continue
        real_root = os.path.realpath(root_dir)
        logger.warning(f"[LMM SEARCH DEBUG] Processing root: {root_dir}, real_root: {real_root}, already_visited: {real_root in visited}")
        if real_root in visited:
            continue
        visited.add(real_root)

        for dirpath, dirnames, filenames in os.walk(root_dir):
            for dname in dirnames:
                if not match_fn(query_lower, dname.lower()):
                    continue
                dir_full_path = os.path.join(dirpath, dname).replace("\\", "/")
                real_dir_path = os.path.realpath(dir_full_path)
                if real_dir_path in visited:
                    continue
                visited.add(real_dir_path)
                try:
                    stats = os.stat(dir_full_path)
                    all_items.append(_build_item(dir_full_path, dname, stats, 'dir', metadata_store=metadata))
                except (PermissionError, FileNotFoundError):
                    continue

            for fname in filenames:
                if not match_fn(query_lower, fname.lower()):
                    continue
                ext = os.path.splitext(fname)[1].lower()
                if ext not in all_extensions:
                    continue

                raw_full_path = os.path.join(dirpath, fname)
                full_path = raw_full_path.replace("\\", "/")
                real_path = os.path.realpath(raw_full_path)
                if real_path in visited:
                    logger.warning(f"[LMM SEARCH DEBUG] SKIP duplicate file: {full_path} (realpath: {real_path})")
                    continue
                visited.add(real_path)
                try:
                    stats = os.stat(raw_full_path)
                    item_type = _ext_to_type(ext)
                    if item_type:
                        if len(all_items) < 5:
                            logger.warning(f"[LMM SEARCH DEBUG] ADD file [{len(all_items)}]: {full_path} (realpath: {real_path})")
                        all_items.append(_build_item(full_path, fname, stats, item_type, metadata_store=metadata))
                except (PermissionError, FileNotFoundError):
                    continue
    return all_items

def _scan_search(roots, query_lower):
    """Pure computation: recursively search directories for files matching query."""
    all_extensions = set(SUPPORTED_IMAGE_EXTENSIONS + SUPPORTED_VIDEO_EXTENSIONS + SUPPORTED_AUDIO_EXTENSIONS)
    metadata = load_metadata()

    visited = set()
    all_items = _search_walk(roots, query_lower, metadata, all_extensions, visited, matches_query)

    is_fuzzy = False
    if not all_items and '*' not in query_lower and '?' not in query_lower:
        visited.clear()
        all_items = _search_walk(roots, query_lower, metadata, all_extensions, visited, fuzzy_match)
        if all_items:
            is_fuzzy = True

    logger.warning(f"[LMM SEARCH DEBUG] _scan_search returning {len(all_items)} items, is_fuzzy: {is_fuzzy}")
    if len(all_items) >= 2:
        logger.warning(f"[LMM SEARCH DEBUG] First 2 items: [{all_items[0]['path']}, {all_items[1]['path']}]")
    return {'items': all_items, 'fuzzy': is_fuzzy}


async def get_search_results(roots, query, force_refresh=False):
    """Cached async wrapper around _scan_search with per-key coalescing."""
    query_lower = query.lower()
    sorted_roots = ":".join(sorted(roots))
    cache_key = f"search:{query_lower}:{sorted_roots}"
    if not force_refresh:
        cached = dir_cache.get(cache_key)
        if cached is not None:
            return cached
    async with dir_cache.lock_for(cache_key):
        if not force_refresh:
            cached = dir_cache.get(cache_key)
            if cached is not None:
                return cached
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _scan_search, roots, query_lower)
        dir_cache.put(cache_key, result)
        return result

def _resolve_scope_roots(search_scopes, directory):
    comfy_dir = os.path.dirname(os.path.dirname(NODE_DIR))
    input_dir = os.path.join(comfy_dir, "input")
    output_dir = os.path.join(comfy_dir, "output")
    roots = []
    for scope in search_scopes:
        if scope == 'current':
            if directory:
                roots.append(directory)
        elif scope == 'input':
            roots.append(input_dir)
        elif scope == 'output':
            roots.append(output_dir)
        elif scope == 'saved':
            config = load_config()
            saved = config.get("saved_paths", [])
            for sp in saved:
                if sp:
                    abs_sp = sp if os.path.isabs(sp) else os.path.join(comfy_dir, sp)
                    roots.append(abs_sp)
    return roots

@prompt_server.routes.get("/local_image_gallery/images")
async def get_local_images(request):
    directory = request.query.get('directory', '')
    search_mode = request.query.get('search_mode', 'local')
    search_query = request.query.get('search_query', '').strip()
    search_scopes = request.query.getall('search_scope', ['current'])
    selected_paths = request.query.getall('selected_paths', [])
    force_refresh = request.query.get('force_refresh', 'false').lower() == 'true'

    if not search_query and search_mode == 'local' and not directory:
        return web.json_response({"error": "Directory not found."}, status=404)

    show_images = request.query.get('show_images', 'true').lower() == 'true'
    show_videos = request.query.get('show_videos', 'false').lower() == 'true'
    show_audio = request.query.get('show_audio', 'false').lower() == 'true'

    filter_tags_str = request.query.get('filter_tag', '').strip().lower()
    filter_tags = [tag.strip() for tag in filter_tags_str.split(',') if tag.strip()]
    filter_mode = request.query.get('filter_mode', 'OR').upper()

    page = int(request.query.get('page', 1))
    per_page = int(request.query.get('per_page', 50))
    sort_by = request.query.get('sort_by', 'name')
    sort_order = request.query.get('sort_order', 'asc')

    all_items_with_meta = []
    is_fuzzy = False

    try:
        def check_tags(item_tags):
            lower_item_tags = [t.lower() for t in item_tags]
            if not filter_tags:
                return True
            if filter_mode == 'AND':
                return all(ft in lower_item_tags for ft in filter_tags)
            else:
                return any(ft in lower_item_tags for ft in filter_tags)

        if search_query:
            comfy_dir = os.path.dirname(os.path.dirname(NODE_DIR))
            roots = _resolve_scope_roots(search_scopes, directory)

            search_result = await get_search_results(roots, search_query, force_refresh)
            search_items = search_result['items']
            is_fuzzy = search_result['fuzzy']
            comfy_prefix = comfy_dir.rstrip("/") + "/"
            for item in search_items:
                if item['path'].startswith(comfy_prefix):
                    item = {**item, 'path': item['path'][len(comfy_prefix):]}
                if not check_tags(item.get('tags', [])):
                    continue
                item_type = item['type']
                if (item_type == 'dir' or
                    (show_images and item_type == 'image') or
                    (show_videos and item_type == 'video') or
                    (show_audio and item_type == 'audio')):
                    all_items_with_meta.append(item)

        elif search_mode == 'global' and filter_tags:
            roots = _resolve_scope_roots(search_scopes, directory)
            resolved_roots = [os.path.realpath(r).rstrip(os.sep) + os.sep for r in roots]
            metadata = load_metadata() if resolved_roots else {}
            for path, meta in metadata.items():
                real_path = os.path.realpath(path)
                if not any(real_path.startswith(root) or real_path.rstrip(os.sep) + os.sep == root for root in resolved_roots):
                    continue
                if os.path.exists(path):
                    if check_tags(meta.get('tags', [])):
                        ext = os.path.splitext(path)[1].lower()
                        item_type = ''
                        if show_images and ext in SUPPORTED_IMAGE_EXTENSIONS: item_type = 'image'
                        elif show_videos and ext in SUPPORTED_VIDEO_EXTENSIONS: item_type = 'video'
                        elif show_audio and ext in SUPPORTED_AUDIO_EXTENSIONS: item_type = 'audio'
                        if item_type:
                            try:
                                stats = os.stat(path)
                                all_items_with_meta.append(_build_item(path, os.path.basename(path), stats, item_type, meta=meta))
                            except Exception: continue

        elif search_mode == 'local':
            directory_items = await get_directory_data(directory, force_refresh)
            if directory_items is None:
                return web.json_response({"error": "Directory not found or is invalid."}, status=404)

            for item in directory_items:
                if not check_tags(item.get('tags', [])):
                    continue

                item_type = item['type']
                if (item_type == 'dir' or
                    (show_images and item_type == 'image') or
                    (show_videos and item_type == 'video') or
                    (show_audio and item_type == 'audio')):
                    all_items_with_meta.append(item)

        if selected_paths:
            pinned_items_dict = {path: None for path in selected_paths}
            remaining_items = []
            for item in all_items_with_meta:
                path = item.get('path')
                if path in pinned_items_dict:
                    pinned_items_dict[path] = item
                else:
                    remaining_items.append(item)

            pinned_items = []
            for path in selected_paths:
                if pinned_items_dict[path]:
                    pinned_items.append(pinned_items_dict[path])

            all_items_with_meta = remaining_items

        reverse_order = sort_order == 'desc'
        if sort_by == 'date': all_items_with_meta.sort(key=lambda x: x['mtime'], reverse=reverse_order)
        elif sort_by == 'rating': all_items_with_meta.sort(key=lambda x: x.get('rating', 0), reverse=reverse_order)
        else: all_items_with_meta.sort(key=lambda x: x['name'].lower(), reverse=reverse_order)

        is_search_result = bool(search_query) or (search_mode == 'global' and filter_tags)

        if not is_search_result:
            all_items_with_meta.sort(key=lambda x: x['type'] != 'dir')

        if selected_paths and pinned_items:
            all_items_with_meta = pinned_items + all_items_with_meta

        parent_directory = os.path.dirname(directory) if not is_search_result else None
        if parent_directory == directory: parent_directory = None

        start = (page - 1) * per_page
        end = start + per_page
        paginated_items = all_items_with_meta[start:end]

        response_data = {
            "items": paginated_items, "total_pages": (len(all_items_with_meta) + per_page - 1) // per_page,
            "current_page": page, "current_directory": directory, "parent_directory": parent_directory,
            "is_global_search": is_search_result
        }
        if is_fuzzy:
            response_data["fuzzy"] = True
        return web.json_response(response_data)
    except Exception as e:
        print(f"LMM Error: {e}")
        return web.json_response({"error": str(e)}, status=500)

@prompt_server.routes.post("/local_image_gallery/set_ui_state")
async def set_ui_state(request):
    try:
        data = await request.json()
        node_id = str(data.get("node_id"))
        gallery_id = str(data.get("gallery_id"))
        state = data.get("state", {})
        if not node_id or not gallery_id:
            return web.json_response({"status": "error", "message": "node_id or gallery_id is required"}, status=400)

        node_key = f"{gallery_id}_{node_id}"
        ui_states = load_ui_state()
        if node_key not in ui_states:
            ui_states[node_key] = {}
        ui_states[node_key].update(state)
        save_ui_state(ui_states)
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=500)

@prompt_server.routes.post("/local_image_gallery/get_selected_items")
async def get_selected_items(request):
    try:
        data = await request.json()
        selection = data.get("selection", [])

        metadata = load_metadata()
        all_items_with_meta = []

        for item_data in selection:
            path = item_data.get("path")
            if path and os.path.exists(path):
                try:
                    stats = os.stat(path)
                    item_type = item_data.get("type")
                    all_items_with_meta.append(_build_item(path, os.path.basename(path), stats, item_type, metadata_store=metadata))
                except (PermissionError, FileNotFoundError):
                    continue

        return web.json_response({
            "items": all_items_with_meta,
            "total_pages": 1,
            "current_page": 1,
            "current_directory": "Selected Items",
            "parent_directory": None,
            "is_global_search": False
        })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@prompt_server.routes.get("/local_image_gallery/get_ui_state")
async def get_ui_state(request):
    try:
        node_id = request.query.get('node_id')
        gallery_id = request.query.get('gallery_id')
        if not node_id or not gallery_id:
            return web.json_response({"error": "node_id or gallery_id is required"}, status=400)

        node_key = f"{gallery_id}_{node_id}"
        ui_states = load_ui_state()

        default_state = {
            "last_path": "",
            "selection": [],
            "sort_by": "name",
            "sort_order": "asc",
            "show_images": True,
            "show_videos": False,
            "show_audio": False,
            "filter_tag": "",
            "search_query": "",
            "search_scopes": ["current", "input", "output", "saved"]
        }

        node_saved_state = ui_states.get(node_key, {})

        final_state = {**default_state, **node_saved_state}

        return web.json_response(final_state)
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=500)

def get_thumbnail_cache_path(filepath, is_video=False):
    filename = hashlib.md5(filepath.encode('utf-8')).hexdigest()
    return os.path.join(THUMBNAIL_CACHE_DIR, filename + ".webp")

@prompt_server.routes.get("/local_image_gallery/thumbnail")
async def get_thumbnail(request):
    filepath = validate_path(urllib.parse.unquote(request.query.get('filepath', '')))
    if not filepath: return web.Response(status=400)
    if not os.path.exists(filepath): return web.Response(status=404)

    ext = os.path.splitext(filepath)[1].lower()
    is_video = ext in SUPPORTED_VIDEO_EXTENSIONS

    cache_path = get_thumbnail_cache_path(filepath, is_video)

    if os.path.exists(cache_path) and os.path.getmtime(cache_path) > os.path.getmtime(filepath):
        return web.FileResponse(cache_path)

    try:
        if is_video:
            try:
                video_cap = cv2.VideoCapture(filepath)
                if not video_cap.isOpened():
                    raise IOError("Cannot open video file")
                ret, frame = video_cap.read()
                if not ret:
                    raise ValueError("Cannot read frame from video")

                img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                img.thumbnail([320, 320], Image.LANCZOS)
                img.save(cache_path, "WEBP", quality=80)
            finally:
                if 'video_cap' in locals() and video_cap.isOpened():
                    video_cap.release()
        else:
            img = Image.open(filepath)
            img.thumbnail([320, 320], Image.LANCZOS)
            img.save(cache_path, "WEBP", quality=85)

        return web.FileResponse(cache_path)
    except Exception as e:
        print(f"LocalMediaManager: Error generating thumbnail for {filepath}: {e}")
        return web.Response(status=500)

@prompt_server.routes.get("/local_image_gallery/view")
async def view_image(request):
    filepath = validate_path(urllib.parse.unquote(request.query.get('filepath', '')))
    if not filepath: return web.Response(status=400)
    if not os.path.exists(filepath): return web.Response(status=404)
    try: return web.FileResponse(filepath)
    except: return web.Response(status=500)

@prompt_server.routes.post("/local_image_gallery/delete_files")
async def delete_files(request):
    try:
        data = await request.json()
        filepaths = data.get("filepaths", [])
        if not isinstance(filepaths, list):
            return web.json_response({"status": "error", "message": "Invalid data format."}, status=400)

        metadata = load_metadata()
        metadata_changed = False

        dir_cache.invalidate()

        for filepath in filepaths:
            filepath = validate_path(filepath)
            if not filepath:
                continue
            if not os.path.isfile(filepath):
                continue
            try:
                ext = os.path.splitext(filepath)[1].lower()
                is_video = ext in SUPPORTED_VIDEO_EXTENSIONS
                cache_path = get_thumbnail_cache_path(filepath, is_video)
                if os.path.exists(cache_path):
                    os.remove(cache_path)

                send2trash(os.path.normpath(filepath))

                if filepath in metadata:
                    del metadata[filepath]
                    metadata_changed = True
            except Exception as e:
                print(f"LMM: Error sending file to trash {os.path.normpath(filepath)}: {e}")

        if metadata_changed:
            save_metadata(metadata)

        return web.json_response({"status": "ok", "message": "Delete operation completed."})
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=500)

@prompt_server.routes.post("/local_image_gallery/move_files")
async def move_files(request):
    dir_cache.invalidate()
    try:
        data = await request.json()
        source_paths = data.get("source_paths", [])
        destination_dir = data.get("destination_dir")

        if not isinstance(source_paths, list) or not destination_dir:
            return web.json_response({"status": "error", "message": "Invalid data format."}, status=400)

        normalized_destination_dir = validate_path(destination_dir)

        if not normalized_destination_dir or not os.path.isdir(normalized_destination_dir):
            return web.json_response({"status": "error", "message": "Invalid or unsafe destination directory."}, status=400)

        metadata = load_metadata()
        metadata_changed = False
        errors = []

        for original_source_path in source_paths:
            try:
                normalized_source_path = validate_path(original_source_path)

                if not normalized_source_path or not os.path.isfile(normalized_source_path):
                    continue

                source_dir = os.path.dirname(normalized_source_path)
                if source_dir == normalized_destination_dir:
                    continue

                filename = os.path.basename(normalized_source_path)
                final_destination_path = os.path.join(normalized_destination_dir, filename)

                counter = 1
                file_base, file_ext = os.path.splitext(filename)
                while os.path.exists(final_destination_path):
                    new_filename = f"{file_base} ({counter}){file_ext}"
                    final_destination_path = os.path.join(normalized_destination_dir, new_filename)
                    counter += 1

                ext = os.path.splitext(normalized_source_path)[1].lower()
                is_video = ext in SUPPORTED_VIDEO_EXTENSIONS
                old_cache_path = get_thumbnail_cache_path(normalized_source_path, is_video)
                if os.path.exists(old_cache_path):
                    os.remove(old_cache_path)

                shutil.move(normalized_source_path, final_destination_path)

                if original_source_path in metadata:
                    metadata[final_destination_path] = metadata[original_source_path]
                    del metadata[original_source_path]
                    metadata_changed = True

            except Exception as e:
                filename_for_error = os.path.basename(original_source_path)
                error_message = f"Could not move '{filename_for_error}': {e}"
                print(f"LMM: {error_message}")
                errors.append(error_message)

        if metadata_changed:
            save_metadata(metadata)

        return web.json_response({"status": "ok", "message": "Move operation completed.", "errors": errors})
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=500)

@prompt_server.routes.post("/local_image_gallery/rename_file")
async def rename_file(request):
    dir_cache.invalidate()
    try:
        data = await request.json()
        old_path = data.get("old_path")
        new_name = data.get("new_name")

        old_path = validate_path(old_path)
        if not old_path or not os.path.isfile(old_path):
            return web.json_response({"status": "error", "message": "Invalid or non-existent source file."}, status=400)

        if not new_name or "/" in new_name or "\\" in new_name:
            return web.json_response({"status": "error", "message": "Invalid new filename."}, status=400)

        directory = os.path.dirname(old_path)
        new_path = os.path.join(directory, new_name)

        if old_path == new_path:
            return web.json_response({"status": "ok", "message": "Filename is the same, no action taken."})

        if os.path.exists(new_path):
            return web.json_response({"status": "error", "message": "A file with that name already exists."}, status=409)

        ext = os.path.splitext(old_path)[1].lower()
        is_video = ext in SUPPORTED_VIDEO_EXTENSIONS
        old_cache_path = get_thumbnail_cache_path(old_path, is_video)
        if os.path.exists(old_cache_path):
            new_cache_path = get_thumbnail_cache_path(new_path, is_video)
            os.rename(old_cache_path, new_cache_path)

        os.rename(old_path, new_path)

        metadata = load_metadata()
        if old_path in metadata:
            metadata[new_path] = metadata[old_path]
            del metadata[old_path]
            save_metadata(metadata)

        return web.json_response({"status": "ok", "message": "File renamed successfully.", "new_path": new_path})
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=500)

@prompt_server.routes.post("/local_image_gallery/save_mask")
async def save_mask(request):
    try:
        data = await request.json()
        image_path = data.get("image_path")
        mask_data_base64 = data.get("mask_data")

        if not image_path or not mask_data_base64:
            return web.json_response({"status": "error", "message": "Missing parameters"}, status=400)

        filename = os.path.basename(image_path)
        name, _ = os.path.splitext(filename)
        input_dir = folder_paths.get_input_directory()

        mask_filename = f"{name}_mask.png"
        mask_path = os.path.join(input_dir, mask_filename)

        img_data = base64.b64decode(mask_data_base64.split(',')[1])
        with Image.open(io.BytesIO(img_data)) as img:
            if 'A' in img.getbands():
                mask_img = img.split()[-1]
            else:
                mask_img = img.convert("L")

            extrema = mask_img.getextrema()
            if extrema and extrema[1] == 0:
                if os.path.exists(mask_path):
                    os.remove(mask_path)
                    print(f"LMM: Empty mask detected, deleted {mask_filename}")
                else:
                    print("LMM: Empty mask detected, nothing to save.")

                return web.json_response({"status": "ok", "message": "Empty mask, file cleared"})

            mask_img.save(mask_path, "PNG")

        return web.json_response({"status": "ok", "mask_path": mask_path})
    except Exception as e:
        print(f"LMM Error saving mask: {e}")
        return web.json_response({"status": "error", "message": str(e)}, status=500)

@prompt_server.routes.post("/local_image_gallery/delete_mask")
async def delete_mask(request):
    try:
        data = await request.json()
        image_path = data.get("image_path")

        if not image_path:
            return web.json_response({"status": "error", "message": "Missing image_path"}, status=400)

        filename = os.path.basename(image_path)
        name, _ = os.path.splitext(filename)
        input_dir = folder_paths.get_input_directory()
        mask_filename = f"{name}_mask.png"

        deleted = False

        input_mask_path = os.path.join(input_dir, mask_filename)
        if os.path.exists(input_mask_path):
            os.remove(input_mask_path)
            deleted = True

        original_dir_mask_path = os.path.join(os.path.dirname(image_path), mask_filename)
        if os.path.exists(original_dir_mask_path):
            os.remove(original_dir_mask_path)
            deleted = True

        if deleted:
            return web.json_response({"status": "ok", "message": "Mask deleted"})
        else:
            return web.json_response({"status": "ok", "message": "No mask found to delete"})

    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=500)

@prompt_server.routes.post("/local_image_gallery/get_mask_path")
async def get_mask_path(request):
    try:
        data = await request.json()
        image_path = data.get("image_path")

        if not image_path:
            return web.json_response({"status": "error", "message": "Missing image_path"}, status=400)

        filename = os.path.basename(image_path)
        name, _ = os.path.splitext(filename)
        input_dir = folder_paths.get_input_directory()

        input_mask_path = os.path.join(input_dir, f"{name}_mask.png")
        if os.path.exists(input_mask_path):
             return web.json_response({"status": "ok", "mask_path": input_mask_path})

        original_dir_mask_path = os.path.join(os.path.dirname(image_path), f"{name}_mask.png")
        if os.path.exists(original_dir_mask_path):
             return web.json_response({"status": "ok", "mask_path": original_dir_mask_path})

        return web.json_response({"status": "ok", "mask_path": None})

    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=500)

NODE_CLASS_MAPPINGS = {
    "LocalMediaManagerNode": LocalMediaManagerNode,
    "SelectOriginalImageNode": SelectOriginalImageNode,
    "SelectOriginalVideoNode": SelectOriginalVideoNode,
    "SelectOriginalAudioNode": SelectOriginalAudioNode,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "LocalMediaManagerNode": "Local Media Manager",
    "SelectOriginalImageNode": "Select Original Image",
    "SelectOriginalVideoNode": "Select Original Video",
    "SelectOriginalAudioNode": "Select Original Audio",
}
