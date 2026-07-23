# 拼豆图纸生成器（PBPG）

一款基于 Python 与 PySide6 的桌面拼豆图纸制作工具。它可以把普通图片转换为指定网格尺寸和色板范围内的拼豆图纸，并支持手工修正、工程保存及多格式导出。

当前版本：`2.0.0`

## 主要功能

- 导入 PNG、JPEG、WebP、BMP 图片并生成拼豆图纸
- 自定义网格尺寸、底板尺寸和最大颜色数量
- 使用 CIEDE2000 色差算法匹配最接近的拼豆颜色
- 支持 Floyd–Steinberg 抖动、透明度阈值和孤点简化
- 调整亮度、对比度、饱和度、锐度、旋转及翻转
- 管理色板中的启用颜色、色号、名称与库存
- 使用画笔、橡皮和取色器手工修改生成结果
- 支持撤销、重做、缩放和网格显示
- 保存和打开 `.pbpg` 工程，并提供自动保存与异常恢复
- 导出 PNG、PDF、SVG 和 CSV 文件

## 快速开始

### 使用 Windows 成品包

1. 解压项目目录中的 `PBPG.zip`。
2. 打开解压后的 `PBPG` 文件夹。
3. 双击 `PBPG.exe` 启动程序。

请保留 `PBPG.exe`、`_internal` 目录及其他随包文件的相对位置，不要只单独复制可执行文件。

### 从源码运行

需要 Python 3.11 或更高版本。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install PySide6 Pillow numpy
python -m perler_pattern
```

## 使用方法

1. 启动程序后，新建空白工程或打开已有的 `.pbpg` 工程。
2. 点击“导入图片”，选择需要转换的原图。
3. 设置网格宽高、底板尺寸、最大颜色数和图像适配方式。
4. 根据需要调整抖动、透明度阈值、亮度、对比度等参数。
5. 在色板中启用需要使用的颜色，并可填写库存数量。
6. 点击“生成图纸”，等待预览完成。
7. 使用画笔、橡皮、取色器及撤销/重做功能修正图纸。
8. 保存 `.pbpg` 工程，或导出为 PNG、PDF、SVG、CSV。

## 支持的文件格式

| 类型 | 格式 |
| --- | --- |
| 导入图片 | `.png`、`.jpg`、`.jpeg`、`.webp`、`.bmp` |
| 工程文件 | `.pbpg` |
| 导入色板 | `.json`、`.csv` |
| 导出图纸 | `.png`、`.pdf`、`.svg`、`.csv` |

单张导入图片最大为 256 MiB。

## 自定义色板

程序支持 JSON 和 CSV 色板。颜色值应使用大写的六位十六进制格式，例如 `#FFCC00`；色号在同一色板中不能重复。

### JSON 示例

```json
{
  "id": "my-palette",
  "name": "我的色板",
  "colors": [
    {
      "code": "A01",
      "name": "亮黄色",
      "hex": "#FFCC00",
      "enabled": true,
      "stock": 100
    }
  ]
}
```

### CSV 示例

```csv
code,name,hex,enabled,stock
A01,亮黄色,#FFCC00,true,100
A02,白色,#FFFFFF,true,
```

CSV 必须包含 `code`、`name`、`hex` 三列；`enabled` 和 `stock` 为可选列。文件编码支持 UTF-8、UTF-8 BOM 和 GB18030。

## 数据与日志

程序运行数据保存在项目或程序目录下的 `.pbpg_data` 文件夹中，其中包括：

- `logs/application.log`：运行日志
- `autosave/`：未命名工程的自动恢复文件
- `settings.ini`：窗口与界面设置（打包版本中生成）

已保存工程的自动恢复副本通常位于工程文件旁，名称类似 `.example.pbpg.autosave.pbpg`。程序每 60 秒尝试自动保存一次有改动的工程。

## 打包 Windows 应用

项目已提供 `PBPG.spec`，安装 PyInstaller 后可直接构建：

```powershell
python -m pip install pyinstaller
pyinstaller PBPG.spec
```

构建结果位于 `dist\PBPG\`。

## 项目结构

```text
perler_pattern/
├── domain/          # 工程模型与编辑会话
├── infrastructure/  # 工程、色板、恢复与导出
├── presentation/    # PySide6 图形界面
├── processing/      # 图片读取、颜色匹配与图纸生成
└── resources/       # 默认色板与应用图标
```

## 常用快捷键

| 操作 | 快捷键 |
| --- | --- |
| 打开工程 | `Ctrl+O` |
| 保存工程 | `Ctrl+S` |
| 另存为 | `Ctrl+Shift+S` |
| 撤销 | `Ctrl+Z` |
| 重做 | `Ctrl+Y` |
| 画笔 | `B` |
| 橡皮 | `E` |
| 取色器 | `I` |

