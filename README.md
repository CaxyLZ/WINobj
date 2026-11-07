# WINobj 3D桌面宠物

一个用 Python 编写的 3D 桌面宠物程序。支持加载 `.obj`、`.glb`、`.gltf`、`.usdz`（以及解压后的 `.usdc`/`.usda`）模型，也可以直接丢进 Sketchfab 下载的 `.zip` 包；并具备物理碰撞、重力下落、鼠标拖拽和键盘翻转功能。

## 功能特性

- 自定义模型：支持 `.obj`（含 `.mtl` 贴图）、`.glb`、`.gltf`、`.usdz`、解压后的 `.usdc`/`.usda`，以及装着这些文件的 `.zip` 压缩包；贴图自动读取，没有时就提示你手动选图。
- 物理引擎：基于模型网格的边界碰撞，包含重力、弹性、摩擦力。
- 键盘控制：按住鼠标时，可用键盘精准控制 3D 模型的旋转。
- 热重载：在配置面板修改参数或更换模型，保存后即刻生效，无需重启（换更大的模型也行）。
- 自定义音效：可分别设置“按下”和“松开”时的音效。
- 数据集中：所有配置和数据统一保存在系统的 `%APPDATA%\WINobj` 文件夹。

## 支持的模型格式

| 格式 | 说明 | 额外依赖 |
| --- | --- | --- |
| `.obj` | Wavefront OBJ，建议和 `.mtl`、贴图放在一起 | 无 |
| `.glb` | glTF 二进制单文件，贴图内嵌，**最推荐** | 无 |
| `.gltf` | 需要同目录的 `.bin` 与贴图文件；建议直接选装它们的 `.zip` | 无 |
| `.usdz` | Pixar USDZ（Apple AR 常用格式） | `pip install usd-core` |
| `.usdc` / `.usda` / `.usd` | USDZ 解压出来的散文件，贴图放在它旁边（子目录也行） | `pip install usd-core` |
| `.zip` | 自动解包并挑出里面的模型文件 | 无 |

**扩展名不对也能读。** 程序是看文件内容（文件头）认格式的，不是看扩展名——下载工具把 `model.glb` 改成 `.circ`、`.bin` 或者干脆没扩展名，照样能打开。在文件对话框里选「所有文件（扩展名被改过也能读）」即可。压缩包里文件被改过名也能认出来。

**Sketchfab 怎么用**：在模型页面点 *Download 3D Model*，下载 **GLB**（单文件、贴图内嵌，最省事）、**glTF**（建议下载后直接选那个 `.zip`）或 **USDZ** 都行——程序现在都能直接打开，不需要额外转换工具。下载的是“原始格式”压缩包（比如 obj+贴图）时，直接选 `.zip` 也能读。USDZ 你也可以解压成 `scene.usdc` + 贴图目录再丢进来，效果完全一样。

> USD 系（`.usdz` / `.usdc` / `.usda`）需要一个可选的解析库：`pip install usd-core`（Pixar 官方 OpenUSD，Windows 上约 13 MB）。没装的时候程序会提示你怎么装，其它格式照常使用。
> 打包 exe 时需要一起带上它，PyInstaller 用 `--collect-all pxr`，否则 exe 里读不了 USD 模型。

## 操作说明

- 鼠标左键按住：拖拽移动模型。
- 按住模型时按键：W/S（横向旋转）、A/D（纵向旋转）、Q/E（平面旋转）。
- 鼠标左键松开：根据鼠标挥动速度和键盘旋转速度甩出模型。
- ESC 键：直接退出程序。
- 系统托盘：右键点击图标可打开配置面板或退出。

## 下载与使用

1. 在仓库右侧的 Releases 页面下载最新的 `WINobj.exe`。
2. 双击运行，首次启动会提示选择模型文件。
3. 程序无需安装 Python 环境。

### 从源码运行

```bash
pip install PySide6 moderngl trimesh pillow numpy
pip install usd-core   # 可选，只为了打开 .usdz / .usdc
python WINobj.py
```

（`scipy` 可选，装上会让 trimesh 用更快的法线算法；不装也很快，程序内置了 numpy 版本的快速顶点法线。）

## 开源协议

MIT License
