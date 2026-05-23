<div align="center">

# ComfyUI Local Media Manager
### The Ultimate Local File Manager for Images, Videos, and Audio in ComfyUI
### 一个为 ComfyUI 打造的终极本地图片、视频、音频媒体管理器

</div>

![QQ截图20250821133258 (1)](https://github.com/user-attachments/assets/efbbd721-6b75-4bdc-be9f-5988474fbc0f)

---

## 🇬🇧 English

### Changelog (2025-12-03)
* **Integrated Lightweight Mask Editor**: Added a seamless, built-in mask editor without bloating the codebase.
    * **Intuitive Controls**: Draw (Left Click), Erase (Shift + Left Click), Pan (Middle Click/Drag), and Smooth Zoom (Mouse Wheel).
    * **Smart Auto-Masking**: Automatically generates a mask from the alpha channel when opening transparent images.
    * **Enhanced UX**: Features "Negative" blend mode display for high visibility, a dynamic cursor that scales with zoom, and a real-time status bar (Resolution & Zoom %).
    * **File Sync**: "Save" writes standard mask files to the `input` directory; "Clear" automatically deletes the mask file, keeping your folders clean.
* **Smart Node Outputs**:
    * **Intelligent RGB Conversion**: The `IMAGE` output now automatically detects and removes the alpha channel if the image is fully opaque, preventing errors with nodes that require RGB input.
    * **Smart Path Fallback**: The `path` output now returns the current directory path when no file is selected, enabling folder-based workflows.
    * **New Output**: Added a dedicated `MASK` output interface.
* **Core Optimizations**:
    * **Lighter Dependencies**: Replaced the heavy `moviepy` dependency with `opencv-python-headless` for faster and lighter video processing.
    * **Robust Refreshing**: Updated `IS_CHANGED` logic to detect external file modifications and mask creations/deletions instantly.
    * **Compatibility**: Improved prompt extraction logic (supporting Civitai formats) and standardized file paths for better cross-platform support.

### Changelog (2025-09-17)
* **Full File Management**: Integrated complete file management capabilities. You can now **Move**, **Delete** (safely to trash), and **Rename** files directly from the UI.
* **Major UI/UX Upgrade**:
    * Replaced the simple path text field with an interactive **Breadcrumb Navigation Bar** for intuitive and fast directory traversal.
    * Added **Batch Action** buttons (`All`, `Move`, `Delete`) to efficiently manage multiple selected files at once.
    * The "Edit Tags" panel now reveals a **Rename** field when a single file is selected for editing.
* **Huge Performance Boost**:
    * Implemented a high-performance **Virtualized Scrolling Gallery**. This dramatically improves performance and reduces memory usage, allowing smooth browsing of folders containing thousands of files.
    * Upgraded the backend with a **Directory Cache** and a robust **Thumbnail Caching System** (including support for video thumbnails) to disk, making subsequent loads significantly faster.
* **Advanced Media Processing Nodes**: Introduced a suite of powerful downstream nodes to precisely control and use your selected media:
    * **Select Original Image**: Selects a specific image from a multi-selection, resizes it with various aspect ratio options, and extracts its embedded prompts.
    * **Select Original Video**: Extracts frames from a selected video with fine-grained controls (frame rate, count, skipping), resizes them, and separates the audio track.
    * **Select Original Audio**: Isolates a specific segment from a selected audio file based on start time and duration.
* **One-Click Workflow Loading**:
    * Now you can load ComfyUI workflows directly from images **and videos** that contain embedded metadata, simply by clicking the new "Workflow" badge.

### Changelog (2025-09-07)
* **Critical Bug Fix**: Fixed a core issue where selecting a new media file while the prompt queue was running could cause the workflow to process the wrong item. The selection is now correctly "locked in" for a task when you queue the prompt, ensuring accurate and predictable results.

### Changelog (2025-09-02)
* **Optimized Unique ID**: Each gallery node now automatically generates and stores its own unique ID, which is synchronized with the workflow. This completely avoids conflicts between different workflows or nodes.

### Update Log (2025-08-31)
* **New Node: Select Original Image**: In multi-image selection mode, this node can be connected to the gallery's “image_path” output interface to retrieve the original image by index. Multiple “Select Original Image” nodes can be used simultaneously.
* **Compact Gallery UI**: A small CSS tweak was made to make the “Local Media Manager” node UI more compact.

### Update Log (2025-08-30)
* **Multi-Select Dropdown**: The previous tag filter has been upgraded to a full-featured multi-select dropdown menu, allowing you to combine multiple tags by checking them.
* **AND/OR Logic Toggle**: A new AND/OR button lets you precisely control the filtering logic for multiple tags (matching all tags vs. matching any tag).

### Update Log (2025-08-27)
* **Major Upgrade**: Implemented a comprehensive **Workflow Memory** system. The node now remembers all UI settings (path, selections, sorting, filters) and restores them on reload.
* **Advanced Features**: Added **Multi-Select** with sequence numbers (`Ctrl+Click`), batch **Tag Editing**, and intelligent **Batch Processing** for images of different sizes.
---

### Overview

**ComfyUI Local Media Manager** is a powerful, all-in-one custom node that brings a complete local file management system directly into your ComfyUI workflow. This single, unified node allows you to browse, manage, rate, tag, and select local images, videos, and audio files, then instantly use them or their metadata in your projects. It eliminates the need to constantly switch to your OS file explorer, dramatically speeding up your creative and organizational process.

The gallery features a high-performance virtualized scrolling layout, a robust caching system, and an advanced lightbox viewer, ensuring a beautiful and efficient management experience even with massive media libraries.

### Features

-   **All-in-One Media Hub**: Browse images, videos, and audio files within a single, powerful node.
-   **Complete File Management**:
    -   **Move**: Move selected files to another directory. Supports path presets for quick access.
    -   **Delete**: Safely sends selected files to the system's Recycle Bin or Trash.
    -   **Rename**: Rename individual files directly within the UI.
-   **Full Metadata Management**:
    -   **Star Rating**: Assign a rating from 1 to 5 stars. Click a star to rate, click it again to unrate.
    -   **Tagging System**: Add or remove custom tags for individual or multiple files at once.
-   **Advanced Navigation & Search**:
    -   Interactive **Breadcrumb Navigation Bar** for easy directory traversal.
    -   **Path Presets** to save and quickly jump to your favorite folders.
    -   **Global Tag Search**: Search for files with specific tags across **all your drives and folders**.
    -   **Multi-Tag Filtering**: Combine multiple tags with **AND/OR** logic for precise searching.
-   **High-Performance Gallery**:
    -   A **virtualized scrolling** waterfall layout that handles thousands of files with ease and low memory usage.
    -   Backend **caching** for directories and thumbnails (including videos) for near-instant loading.
-   **Advanced Lightbox Viewer**:
    -   Double-click any media file to open a full-screen preview.
    -   **Image Viewer**: Supports zooming (mouse wheel) and panning (drag).
    -   **Video/Audio Player**: Provides full playback controls.
    -   **Gallery Navigation**: Use on-screen arrows or keyboard keys to cycle through media.
-   **Workflow Integration**:
    -   **One-Click Workflow Loading** from images and videos via a "Workflow" badge.
    -   A suite of **downstream nodes** for advanced processing of selected media.

### ⚠️ Important Note on Dependencies

To support powerful new features like video processing and safe file deletion, this version requires a few additional Python libraries.

**New Dependencies & Their Purpose:**
* **`moviepy`**: Used to generate thumbnails for video files in the gallery.
* **`opencv-python-headless`**: Powers the frame extraction feature in the `Select Original Video` node.
* **`torchaudio`**: Enables audio processing for the `Select Original Audio` and `Select Original Video` nodes.
* **`send2trash`**: Ensures that deleting files is safer by sending them to the system's Recycle Bin/Trash instead of permanently deleting them.

**Video Backend — PyAV:**

The node uses **PyAV** (the `av` Python package) as its **primary backend** for video thumbnails, video metadata, and loading video frames. PyAV bundles a modern FFmpeg build with `libdav1d`, so it decodes **AV1** (the modern codec used by YouTube and much web video) in-process — fast, no external process, and no system `ffmpeg` required on `PATH`.

When PyAV is not available in the environment, the node automatically falls back to **OpenCV** (`opencv-python`/`cv2`). Note that OpenCV's bundled FFmpeg cannot software-decode AV1, so AV1 files will fail on the cv2 fallback — PyAV is what makes AV1 work reliably. Both `av` and `opencv-python` are listed in `requirements.txt` and installed automatically with the node; no manual setup is needed.

**Installation:**
The easiest way to install these is through the **ComfyUI Manager**. After updating the custom node, the manager should detect the missing dependencies and prompt you to install them.

If you prefer to install them manually, you can navigate to this custom node's directory (`ComfyUI/custom_nodes/ComfyUI_Local_Image_Gallery/`) in your terminal and run:
`pip install -r requirements.txt`

### Installation

1.  Navigate to your ComfyUI installation directory.
2.  Go to the `ComfyUI/custom_nodes/` folder.
3.  Clone or download this repository into the `custom_nodes` folder. The final folder structure should be `ComfyUI/custom_nodes/ComfyUI_Local_Image_Gallery/`.
4.  Restart ComfyUI.

### How to Use

#### 1. Main Node: `Local Media Manager`
This is your central hub for all media operations.

* **Browsing**:
    * Click on the **breadcrumb navigation bar** to jump to parent directories or to manually type/paste a full path and press `Enter`.
    * Use the **Path Presets** dropdown to save and quickly access frequent folders.
    * Click the `⬆️ Up` button to go to the parent directory.
* **Selection**:
    * **Single Select**: Click a card to select it.
    -   **Multi-Select**: `Ctrl+Click` to select multiple files. A sequence number will appear on each selected card.
    -   **Select All**: Click the `All` button to select all visible files.
* **File Management**:
    * With files selected, use the `➔ Move` and `🗑️ Delete` buttons for batch operations.
    * To **Rename**, select a single file, click the `✏️` icon on its card, and the rename field will appear in the "Edit Tags" panel above the gallery.
* **Metadata**:
    -   **Rating**: Click the stars on any card to assign a rating.
    -   **Tagging**: Select one or more files. The "Edit Tags" panel will appear. Type a tag and press `Enter` to add it to all selected files. Click the `ⓧ` on a tag to remove it.

#### 2. Downstream Nodes
Connect these nodes to the outputs of the `Local Media Manager` to process your selections.

* **`Select Original Image`**
    -   **Purpose**: To isolate a single image from a multi-selection and prepare it for your workflow.
    -   **Inputs**:
        -   `paths`: Connect to the `paths` output of the main gallery node.
        -   `index`: The sequence number (0, 1, 2...) of the image you want to select from the batch.
        -   `generation_width`/`height`: Desired output dimensions.
        -   `aspect_ratio_preservation`: How to handle resizing (stretch, crop, etc.).
    -   **Outputs**:
        -   `image`: The processed image tensor.
        -   `positive_prompt`/`negative_prompt`: Extracts prompts from the image's metadata, if available.

* **`Select Original Video`**
    -   **Purpose**: To extract image frames and/or audio from a selected video file.
    -   **Inputs**:
        -   `paths`: Connect to the `paths` output of the main gallery node.
        -   `index`: The sequence number of the video you want to select.
        -   `frame_load_cap`: The maximum number of frames to extract.
        -   `force_rate`: Force a specific frame rate for the output sequence.
        -   `skip_first_frames`: Start extraction after skipping a number of initial frames.
        -   `select_every_nth`: Sample the video by taking only every Nth frame.
    -   **Outputs**:
        -   `IMAGE`: A batch of image frames ready for use.
        -   `audio`: The extracted audio track from the video.

* **`Select Original Audio`**
    -   **Purpose**: To load and trim a specific segment from an audio file.
    -   **Inputs**:
        -   `paths`: Connect to the `paths` output of the main gallery node.
        -   `index`: The sequence number of the audio file you want to select.
        -   `seek_seconds`: The start time (in seconds) for the audio clip.
        -   `duration`: The desired length (in seconds) of the audio clip.
    -   **Outputs**:
        -   `audio`: The trimmed audio data.

---

## 🇨🇳 中文

### 更新日志 (2025-12-04)
* **内置轻量级遮罩编辑器**: 在保持插件轻便的同时，集成了一个功能完备的遮罩编辑器。
    * **操作流畅**: 支持左键绘制、Shift+左键擦除、中键平移画布以及滚轮丝滑缩放。
    * **智能初始化**: 打开带有透明通道的图片时，会自动识别透明区域并生成遮罩笔迹。
    * **交互体验**: 采用“差值（Negative）”模式显示遮罩，确保在任何图片上都清晰可见；光标大小随缩放自动调整，右下角实时显示分辨率与缩放比例。
    * **文件同步**: 遮罩保存为标准图像至 `input` 目录；点击“Clear”不仅清空画布，还会自动物理删除对应的遮罩文件，拒绝垃圾文件残留。
* **智能节点输出**:
    * **自动 RGB 转换**: `IMAGE` 输出接口现在会智能检测，如果图像完全不透明，自动丢弃 Alpha 通道转为 RGB 格式，避免后续节点报错。
    * **路径智能回退**: 当未选择任何文件时，`path` 接口会自动输出当前浏览的文件夹路径，方便连接加载文件夹的节点。
    * **新增接口**: 主节点新增了 `MASK` 输出接口。
* **核心与性能优化**:
    * **移除重型依赖**: 彻底移除了臃肿的 `moviepy` 库，改用 `opencv-python-headless` 处理视频缩略图，启动更快，体积更小。
    * **灵敏刷新**: 重写了 `IS_CHANGED` 逻辑，现在能敏锐感知外部文件的修改以及遮罩文件的创建/删除，自动触发工作流刷新。
    * **兼容性增强**: 增强了对复杂元数据（如 Civitai 格式）的提示词提取能力，并修复了跨平台路径分隔符问题。

### 更新日志 (2025-09-17)
* **完整的文件管理功能**：集成了全面的文件管理能力。现在您可以直接在UI界面中**移动**、**删除**（安全移至回收站）和**重命名**文件。
* **UI/UX 重大升级**：
    * 使用交互式的**面包屑导航栏**替代了原有的纯文本路径输入框，使文件夹跳转更直观、更快捷。
    * 新增了**批量操作**按钮（`All`、`Move`, `Delete`），以高效地同时管理多个选定文件。
    * 当选中单个文件进行编辑时，“编辑标签”面板中会显示**重命名**输入框。
* **巨大的性能提升**：
    * 实现了高性能的**虚拟化滚动图库**。这极大地提升了性能并降低了内存占用，即使是包含数千个文件的文件夹也能流畅浏览。
    * 升级了后端，为目录列表和缩略图（包括新增的视频缩略图支持）提供了强大的**磁盘缓存系统**，显著加快了二次加载速度。
* **新增高级媒体处理节点**：引入了一套强大的下游节点，以精确控制和使用您选择的媒体：
    * **Select Original Image**：从多选的图片中选取指定一张，通过丰富的宽高比选项调整其尺寸，并提取其内嵌的提示词。
    * **Select Original Video**：从指定的视频中提取帧序列，提供精细的控制选项（帧率、数量、跳过帧数），调整尺寸，并分离出音频轨道。
    * **Select Original Audio**：根据开始时间和持续时长，从一个音频文件中精确截取所需的片段。
* **一键加载工作流**：
    * 现在可以从内嵌了元数据的图片**和视频**中直接加载 ComfyUI 工作流，只需单击新增的“Workflow”徽章即可。

### 更新日志 (2025-09-07)
* **重大BUG修复**：修复了一个核心问题，即在任务队列正在处理时选择新的媒体文件，会导致工作流处理错误的选项。现在，当您点击“生成”时，所选的媒体会被正确地“锁定”到该任务中，确保了结果的准确性和可预测性。

### 更新日志 (2025-09-02)
* **优化唯一 ID**：每个图库节点现在都会自动生成并保存其专属的唯一 ID，并与工作流程同步。这完全避免了不同工作流程或节点之间的冲突。

### 更新日志 (2025-08-31)
* **新增节点：Select Original Image**: 在图像多选状态下，可以使用这个节点与图库的“image_path”输出接口相连，选择对应序号获取原始图像，可使用多个“Select Original Image”节点。
* **使图库UI更紧凑**: 修改了一小段CSS式样，使“Local Media Manager”节点UI变得紧凑起来。

### 更新日志 (2025-08-30)
* **多选下拉菜单**: 原有的标签筛选器已升级为功能完善的多选下拉菜单，允许您通过勾选来组合多个标签进行筛选。
* **AND/OR 逻辑切换**: 新增了一个 AND/OR 切换按钮，让您可以精确控制多标签的筛选逻辑（是需要满足所有标签，还是满足任意一个）。

### 更新日志 (2025-08-27)
* **重大升级**: 实现了完整的 **工作流记忆** 系统。节点现在可以记住所有UI设置（路径、选择项、排序、筛选）并在重载后恢复。
* **高级功能**: 新增了带序号的 **多选功能** (`Ctrl+单击`)、批量 **标签编辑**，以及对不同尺寸图片的智能 **批处理**。
---

### 概述

**ComfyUI 本地媒体管理器** 是一个功能强大、一体化的自定义节点，它将一个完整的本地文件管理系统直接集成到了您的 ComfyUI 工作流中。这一个统一的节点允许您浏览、管理、评级、标记和选择本地的图片、视频和音频文件，并能一键将它们本身或其元数据导入到您的项目中。它彻底消除了在操作系统文件浏览器和ComfyUI之间来回切换的烦恼，极大地加速了您的创作和整理流程。

本插件的图库拥有一个高性能的虚拟化滚动布局、强大的缓存系统和一个高级的灯箱预览器，即使面对海量媒体库，也能确保美观且高效的管理体验。

### 功能特性

-   **一体化媒体中心**: 在一个强大的节点内即可浏览图片、视频和音频文件。
-   **完整的文件管理**:
    -   **移动**: 将选中文件移动到其他目录，支持路径预设以便快速访问。
    -   **删除**: 安全地将选中文件移至操作系统的回收站。
    -   **重命名**: 直接在UI界面内重命名单个文件。
-   **完整的元数据管理**:
    -   **星级评分**: 为任何媒体文件赋予1到5星的评级。单击星星即可评分，再次单击可以取消评分。
    -   **标签系统**: 为单个或多个文件批量添加或删除自定义标签。
-   **高级导航与搜索**:
    -   交互式**面包屑导航栏**，轻松进行目录跳转。
    -   **路径预设**功能，用于保存并快速访问常用文件夹。
    -   **全局标签搜索**: 跨越您所有的硬盘和文件夹，搜索带有特定标签的文件。
    -   **多标签筛选**: 使用 **AND/OR** 逻辑组合多个标签，进行精确搜索。
-   **高性能图库**:
    -   **虚拟化滚动**的瀑布流布局，能以极低的内存占用轻松处理数千个文件。
    -   为目录和缩略图（包括视频）提供后端**缓存**，实现近乎秒开的加载速度。
-   **高级灯箱预览器**:
    -   双击任意媒体文件即可打开一个全局全屏预览器。
    -   **图片查看器**: 支持使用鼠标滚轮进行**缩放**，并通过拖动进行**平移**。
    -   **视频/音频播放器**: 提供完整的播放控制功能。
    -   **图库导航**: 使用界面上的箭头或键盘方向键轻松切换浏览媒体。
-   **工作流集成**:
    -   通过“Workflow”徽章从图片和视频中**一键加载工作流**。
    -   提供一套**下游节点**，用于对所选媒体进行高级处理。

### ⚠️ 关于依赖项的重要说明

为了支持视频处理、安全删除文件等强大的新功能，此版本需要安装一些额外的Python库。

**新增依赖及其用途：**
* **`moviepy`**：用于在图库中为视频文件生成缩略图。
* **`opencv-python-headless`**：为 `Select Original Video` 节点提供视频帧提取功能。
* **`torchaudio`**：为 `Select Original Audio` 和 `Select Original Video` 节点提供音频处理能力。
* **`send2trash`**：确保文件删除的安全性，它会将文件移至系统的回收站而不是永久删除。

**安装说明：**
最简单的安装方式是使用 **ComfyUI Manager**。在更新本插件后，管理器会自动检测到缺失的依赖项并提示您进行安装。

如果您希望手动安装，可以打开终端，进入本插件的目录 (`ComfyUI/custom_nodes/ComfyUI_Local_Image_Gallery/`)，然后运行以下命令：
`pip install -r requirements.txt`

### 安装说明

1.  导航至您的 ComfyUI 安装目录。
2.  进入 `ComfyUI/custom_nodes/` 文件夹。
3.  将此插件的仓库克隆或下载到 `custom_nodes` 文件夹中。最终的文件夹结构应为 `ComfyUI/custom_nodes/ComfyUI_Local_Image_Gallery/`。
4.  重启 ComfyUI。

### 使用方法

#### 1. 主节点: `Local Media Manager`
这是您所有媒体操作的中心枢纽。

* **浏览文件**:
    * 点击**面包屑导航栏**可以跳转到上级目录，或者直接点击它来手动输入/粘贴完整路径，然后按`回车`。
    * 使用**路径预设**下拉菜单可以保存并快速访问常用文件夹。
    * 点击 `⬆️ Up` 按钮可以返回上一级目录。
* **选择文件**:
    * **单选**: 单击一个卡片来选中它。
    -   **多选**: 按住 `Ctrl` 并单击卡片，可以选择多个文件。每个选中的文件上会显示一个序号。
    -   **全选**: 点击 `All` 按钮，可以选中当前视图中的所有文件。
* **文件管理**:
    * 选中文件后，使用 `➔ Move` 和 `🗑️ Delete` 按钮进行批量操作。
    * 要**重命名**文件，请先**单选**一个文件，然后点击其卡片右下角的 `✏️` 图标，此时图库上方的“编辑标签”区域会出现重命名输入框。
* **管理元数据**:
    -   **评级**: 点击任意卡片下方的星星来进行评分。
    -   **标签**: 选中一个或多个文件后，“编辑标签”区域即会显示。输入新标签并按`回车`，即可将其添加到所有选中的文件中。点击标签旁的 `ⓧ` 可将其移除。

#### 2. 下游节点
将这些节点连接到 `Local Media Manager` 的输出端口，以处理您选择的媒体。

* **`Select Original Image`**
    -   **用途**: 从多选的图片中分离出特定一张，并为您的工作流做好准备。
    -   **输入**:
        -   `paths`: 连接到主图库节点的 `paths` 输出。
        -   `index`: 您想从批次中选择的图片序号（从0开始）。
        -   `generation_width`/`height`: 期望的输出图像尺寸。
        -   `aspect_ratio_preservation`: 如何处理图像缩放（拉伸、裁剪等）。
    -   **输出**:
        -   `image`: 处理后的图像张量（Tensor）。
        -   `positive_prompt`/`negative_prompt`: 如果图片元数据中存在，则提取其正负提示词。

* **`Select Original Video`**
    -   **用途**: 从选定的视频文件中提取图像帧和/或音频。
    -   **输入**:
        -   `paths`: 连接到主图库节点的 `paths` 输出。
        -   `index`: 您想选择的视频序号。
        -   `frame_load_cap`: 要提取的最大帧数。
        -   `force_rate`: 强制指定输出序列的帧率。
        -   `skip_first_frames`: 从视频开头跳过指定数量的帧后再开始提取。
        -   `select_every_nth`: 通过仅提取每第N帧来进行采样。
    -   **输出**:
        -   `IMAGE`: 一批可直接使用的图像帧。
        -   `audio`: 从视频中提取的音轨。

* **`Select Original Audio`**
    -   **用途**: 从一个音频文件中加载并截取特定片段。
    -   **输入**:
        -   `paths`: 连接到主图库节点的 `paths` 输出。
        -   `index`: 您想选择的音频文件序号。
        -   `seek_seconds`: 音频片段的开始时间（单位：秒）。
        -   `duration`: 您想要的音频片段时长（单位：秒）。
    -   **输出**:
        -   `audio`: 截取后的音频数据。