## 一、Yocto SDK 整体层级关系

### 1.1 仓库形态

本工作区是由 Google `repo` 工具组装的一个**多仓库 Workspace**，不是单个 Git 仓库：

- 顶层 `/mnt/fileroot/teng.wang/Yocto-4.0` 下没有 `.git`。
- 实际的清单文件在 `.repo/manifests/yocto-kirkstone.xml`（入口：`.repo/manifest.xml`）。
- 顶层的 `manifest-base.xml` / `manifest-final.xml` / `BT.xml` 是历史/附加文件，不是真正驱动 `repo sync` 的清单。
- 树级 Git 操作要用 `repo status` / `repo forall`，单个组件级用 `git`。

### 1.2 分层（Yocto Layer）角色

按"能不能改"和"做什么"分成四档：

| 档次 | 目录 | 角色 | 是否可以改 |
|------|------|------|-----------|
| **上游（动不得）** | `poky/` | Yocto/OpenEmbedded 上游核心（Kirkstone） | 不要改 |
|  | `meta-openembedded/`, `meta-gplv2/`, `meta-qt5/`, `meta-security/`, `meta-selinux/`, `meta-python2/` | 第三方上游 meta layer | 不要改 |
| **Amlogic BSP 核心** | `meta-meson/` | **所有 Amlogic 特有 recipe 的家**：SoC/kernel 包含文件、bbclass、`recipes-bsp/`、`recipes-kernel/`、`recipes-multimedia/`、`recipes-platform/`、`recipes-graphics/`、登场脚本 `aml-setenv.sh` | 经常改 |
| **产品/板级配置** | `meta-aml-cfg/` | `conf/machine/*.conf` —— 用户真正 `MACHINE=` 选的那个名字（如 `mesonsc2-ah212-5.15-lib32`） | 新板子在这里加 |
| **OTT/App 集成** | `meta-aml-apps/` | Netflix / YouTube (Cobalt) / Amazon / Disney / GoogleCast / Miracast / Alexa / Samba 的 OTT 接入 | 新增应用在这里 |
| **闭源源码底座** | `aml-comp/` | 由 `repo` 拉下来的 120+ 个独立闭源 Git 项目。**只是源码，不是 layer**；它的内容会被 `meta-meson` / `meta-aml-apps` 的 recipe 消费 | 按模块改 |

### 1.3 `aml-setenv.sh`：连接 layer 和板级 config 的关键脚本

路径：`meta-meson/aml-setenv.sh`，它不是 `oe-init-build-env` 的简单替代，而是在其基础上做了几件 Amlogic 特有的事：

1. 导出 `MESON_ROOT_PATH`，追加 `BB_ENV_PASSTHROUGH_ADDITIONS`。
2. 对 `meta-aml-cfg/conf/machine/*.conf` 做 lunch 菜单，子串过滤。
3. **重新生成** `build-<x>/conf/local.conf` 和 `bblayers.conf`（旧的会被重命名为 `*.old`）——**手改这两个文件会被下次 source 覆盖**。
4. 条件 `BBLAYERS =+` ：存在哪个可选 layer 就加哪个（meta-clang、meta-qt5、meta-security、meta-selinux、meta-thunder、meta-aml-cfg、meta-aml-apps、meta-virtualization 等）。
5. **根据 `aml-comp/` 下子树的存在情况修改 `DISTRO_FEATURES`**——例如没有 `aml-comp/thirdparty/nf-sdk` 就 `remove netflix`，没有 `aml-comp/vendor/amlogic/arka` 就 `remove arka arka-egl`。
6. `*-lib32*` 机器自动打开 multilib（64 位内核 + 32 位用户态）。
7. `*mc*` 机器自动启用 `BBMULTICONFIG="recovery"`。
8. 把 `.repo/manifests/<manifest>.conf` 拷到 `conf/auto.conf` 做版本锁定。

**这条机制意味着：某个 Feature 能不能启用，并不只看 `local.conf`，还看 `aml-comp/` 里相应目录是否真的被 repo sync 下来了。**

### 1.4 构建目录

一个 SoC 系列一个：`build-s7d/`、`build-sc2/`、`build-t5w/`……每个里面有自己的 `conf/`、`tmp/`、`cache/`、`buildhistory/`，但 `downloads/`（指向上层 `../yocto_downloads`）和 `sstate-cache/` 是**共享**的。

### 1.5 分层自上而下的数据流

```
┌──────────────────────────────────────────────────────────────┐
│   .repo / manifest.xml                                       │
│   由 repo 工具同步所有 Git 项目                              │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────┐
│   aml-comp/  (闭源源码：hardware/kernel/multimedia/…)        │
│   不是 layer，只是源码                                        │
└───────────────────────────┬──────────────────────────────────┘
                            │ 被消费
┌───────────────────────────▼──────────────────────────────────┐
│   Yocto Layer（bitbake 识别）                                │
│   ├ poky/                  (上游内核)                         │
│   ├ meta-openembedded/…    (第三方)                          │
│   ├ meta-meson/            (Amlogic BSP recipe + class)       │
│   ├ meta-aml-cfg/          (板级 MACHINE.conf)                │
│   └ meta-aml-apps/         (OTT 应用)                         │
└───────────────────────────┬──────────────────────────────────┘
                            │ source meta-meson/aml-setenv.sh
┌───────────────────────────▼──────────────────────────────────┐
│   build-<soc>/ （自动生成的 conf/）                          │
│   → bitbake <target>                                          │
│   → tmp/deploy/images/<machine>/  固件产出                   │
└──────────────────────────────────────────────────────────────┘
```

---

## 二、`aml-comp/` 模块总览

`aml-comp/` 是**闭源源码底座**，包含 120+ 个独立 Git 项目，按功能域划分为 7 个子树：

| 子树 | 职责 | 关键内容 |
|------|------|---------|
| `hardware/` | SoC 及外设驱动、GPU、无线芯片 | `aml-5.15/amlogic/media_modules`（内核态 codec 驱动）、`amlogic/{libion,libge2d,libgdc,libencoder,npu,cve,wifi}`（用户/内核 helper）、`arm/gpu`（Mali）、`bluetooth/{amlogic,mediatek,realtek}`、`wifi/{amlogic,broadcom,mediatek,qualcomm,realtek}` |
| `kernel/` | 三套内核源码树 | `aml-5.15`、`aml-5.15-U`（Android Common Kernel 风味）、`aml-6.12`。机器 conf 中的 `5.15/6.12` 版本号决定选哪棵树 |
| `multimedia/` | 多媒体全栈：音频 HAL、媒体 SDK、GStreamer 插件、编解码 lib、DVR/CAS、渲染/同步 | **约 40 个独立组件**——本报告第三章重点 |
| `prebuilt/` | 闭源二进制产物，**不要重建**，视为密封 | `hosttools/`（打包器：`aml-image-packer`、`aml-gpt-make`、`aml-linux-sb`、`aml-swupdate`）、`target/`（kernel-module/pq、tuner）、`vendor/`（firmware、logo、recovery_img、wireless）、`dtvkit-release/` |
| `thirdparty/` | 浏览器、显示服务器、Miracast | `cobalt-starboard` / `cobalt-starboard-open`（YouTube/Cobalt）、`miraclecast`、`westeros`、`weston-10` |
| `uboot/` | 完整 boot 栈源码 | `bl2`、`bl30/{bin,rtos_sdk,src_ao}`、`bl31/{1.0,1.3,2.7,2.12}`、`bl32/{2.4,3.8,3.18,4.4}`、`bl33/{v2015,v2019,v2023}`、`bl40`；**`fip/` 是构建驱动器**（`mk_script.sh` 是编排总入口） |
| `vendor/amlogic/` | Amlogic 平台/用户态服务 | `aml-appmanager`、`aml-system-server`、`aml-tvserver`、`aml_platformserver`、`aml_subtitleserver`、`aml_pqserver`、`aml_hdmicec`、`aml_dab`、`aml_swupdate_ui`、`aml_avb_dm_verity`、`arka`/`arka-egl`、`dvb`、`dtvkit`、`dtvdemod`、`hdcp`、`provision`、`efuse`、`tdk`、`meson_display`、`meson_mali`、`meson_videoserver` 等 |

### 关键特性

1. **DISTRO_FEATURES gating**：某些 feature 靠"目录是否存在"来决定要不要构建。比如 `aml-comp/thirdparty/nf-sdk` 缺失 → Netflix 被自动 remove。不要手改 `DISTRO_FEATURES` 绕过缺失，应修 manifest 重 sync。
2. **无 `.git` 的中层**：`aml-comp/` 本身和大部分中间层没有 Git；真正的 Git 仓库在更深处。
3. **`prebuilt/` 是源，不是产物**：里面的 `.so`/`.ta` 是 Amlogic 发的二进制黑盒，别用"重建"来"修复"。
4. **三棵内核树**：`aml-5.15`、`aml-5.15-U`、`aml-6.12`，单棵 >1 GB，文件工具 (`find`、`grep`) 跨树扫非常慢，务必缩范围。

---

## 三、`aml-comp/multimedia/` 深度剖析（核心）

### 3.1 定位

- `multimedia/` 本身**不是** Yocto layer，不是 bitbake 可识别的目录；它纯粹是**约 40 个独立 Git 仓库组成的源码包**。
- 对应的 bitbake recipe 都在 `meta-meson/recipes-multimedia/`。每个组件都**可以独立 build**（直接进目录 make/cmake/meson）或**通过 bitbake 拉起来**。
- 不同组件用的构建系统完全不同（CMake / Plain Makefile / Autotools / Meson / Android.mk），一个组件里甚至多种并存。

### 3.2 全局分层总图

```
┌────────────────────────────────────────────────────────────────────────────┐
│                       应用层（meta-aml-apps / vendor services）            │
│   Netflix   YouTube(Cobalt)   Amazon   DTVKit   aml-player-service   …     │
└────────────┬─────────────────────────────────────────────┬─────────────────┘
             │ 直接使用                                     │ Pipeline
             ▼                                             ▼
┌────────────────────────────────┐     ┌──────────────────────────────────────┐
│   Aml_MP_SDK  (aml_mp_sdk)     │     │   GStreamer 1.x 插件栈                │
│   对外主入口：MediaPlayer /     │     │ ┌──────────────────────────────────┐ │
│   TsPlayer / DVR / Cas /       │     │ │ Demux:  gst-plugin-aml-demux     │ │
│   TunerHal / Common            │     │ │          (hw/qt/ts demux)        │ │
│                                │     │ │         gst-fluendo-mpegdemux    │ │
│   子目录: cas/ demux/ dvr/     │     │ │                                  │ │
│           mediaplayer/ player/ │     │ │ Dec:    gst-plugin-aml-v4l2dec   │ │
│           tunerhal/ utils/     │     │ │                                  │ │
│                                │     │ │ Snk:    gst-plugin-aml-asink     │ │
│                                │     │ │          aml-picsink             │ │
│                                │     │ │          aml-subtitlesink        │ │
│                                │     │ │          video-sink              │ │
│                                │     │ │ Enc:    gst-plugin-venc          │ │
│                                │     │ │ DRM:    gst-aml-drm-plugins1     │ │
│                                │     │ │          gst-aml-drmbufferpool1  │ │
│                                │     │ │          gst-plugin-aml-wlcdmi   │ │
│                                │     │ │ Utils:  gst-aml-utils / gst-app  │ │
│                                │     │ │ HL:     gst_agmplayer            │ │
│                                │     │ └──────────────────────────────────┘ │
└───────┬────────────────────────┘     └──────────┬───────────────────────────┘
        │                                          │
        ▼                                          ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                 媒体/播放/DVR/CAS 中间件（通用库）                          │
│  libplayer        播放核心（历史路径，gitignore 掉 src/）                   │
│  mediahal-sdk     HAL 抽象（预编译 .so 安装器）                             │
│  libdvr           DVR / 时移 / 录像                                         │
│  cas-hal          条件接收 HAL（付费电视解扰统一接口）                     │
│  libmediadrm      CDM 加载：widevine / playready / clearkey / netflix_ta / │
│                   wlcdmi / youtubesign / libsecmem（全部二进制）            │
└────────────────────────────┬───────────────────────────────────────────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                         渲染 / 同步层                                       │
│  libvideorender      视频 render（drm / mesonvideocompositor / videotunnel │
│                      / westeros / weston）                                  │
│  avsync-lib          音视频同步库                                           │
└────────────────────────────┬───────────────────────────────────────────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                        音频 HAL 栈                                          │
│  aml_audio_hal       HAL 核心（audio_hal/, audio_codec/{libdts,libdcv,     │
│                      libmpegh,libvorbis}, audio_client/, encoder/,         │
│                      decoder/, input/, vendor_process/, utils/）            │
│  amaudio             音频内核接口封装                                       │
│  hal_audio_service   音频服务进程                                           │
│  aml_alsa_plugins    ALSA PCM / CTL 插件（`ahal`）                           │
│  aml_amaudioutils    工具库                                                 │
│  audiocapture        音频采集                                               │
│  libaudioeffect      EQ / balance / DBX / DPE / VirtualX 等音效 .so         │
│  dolby_atmos_release Dolby Atmos 闭源解码                                   │
│  dolby_ms12_release  Dolby MS12 闭源                                        │
│  dts_release         DTS 闭源（32bit/64bit 两份）                           │
└────────────────────────────┬───────────────────────────────────────────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                        编解码 / 格式 库                                     │
│  ffmpeg-aml          Amlogic fork（经 meta-meson 的 ffmpeg_4.4.bb 打包）    │
│  ffmpeg_ctc          另一个 fork（另一条 recipe 路径消费，不要混合 patch）  │
│  libfaad libflac libmad libopus libiamf libadpcm  单格式解码                │
└────────────────────────────────────────────────────────────────────────────┘

辅助/跨层：
  secfirmload       TEE 固件加载（secloadbin）
  wifidisplay       Miracast Source
  v4l2-uvm-test     V4L2 UVM 测试工具
  mediasupport      支撑 / 胶水库
  test_tool         spdif_in_dd_decoder 等测试程序
  aml_iptv_firmware IPTV 固件 blob
```

### 3.3 逐组件职责表（按层展开）

#### A. 对外 SDK / 播放框架层

##### `aml_mp_sdk/` —— 最上层入口
这是应用最常用的 C++ SDK，头文件位于 `include/Aml_MP/`：`Aml_MP.h`、`Aml_MediaPlayer.h`、`Cas.h`、`Common.h`、`Dvr.h`。内部目录：

| 子目录 | 职责 |
|--------|------|
| `mediaplayer/` | `Aml_MP_MediaPlayer` 顶层播放器（文件/URL 级），基类 `AmlMediaPlayerBase` + Impl 分离 |
| `player/` | `Aml_MP_Player`：TS-level / TV / CTC / Dummy 多种 player 实现（`AmlTsPlayer`、`AmlTvPlayer`、`AmlCTCPlayer`、`AmlDummyTsPlayer`） |
| `demux/` | `AmlDemuxBase` 基类 + `AmlHwDemux` / `AmlSwDemux` / `AmlTunerHalDemux`；`AmlTsParser` 解 PSI/SI |
| `dvr/` | `AmlDVRPlayer` / `AmlDVRRecorder`（底层调 `libdvr`） |
| `cas/` | `AmlCasBase` → `AmlDvbCasHal` / `AmCasLibWrapper` + `nagra_webcas`、`vmx_iptvcas`、`vmx_webcas`、`wv_iptvcas` 等 CAS 扩展 |
| `tunerhal/` | 与 Android Tuner HAL 对接（`TunerService`、`TunerDemux`、`TunerFilter`、`TunerDvr`、`AudioTrackWrapper`、`MediaCodecWrapper`） |
| `utils/` | 事件循环 / FIFO / buffer / message / looper 等基础设施（`AmlMpEventLooper`、`AmlMpMessage`、`AmlMpBitReader`、`AmlMpChunkFifo`…） |
| `tests/` | 自测程序 |

**构建**：同时带 `CMakeLists.txt`（主用）、`Makefile`、`Android.mk`（兼容老下游）。动 `include/Aml_MP/*` 头时，务必 `bitbake -p` 检查所有 RDEPENDS。

##### `mediahal-sdk/` —— 特殊：伪装成源码的二进制安装器
`Makefile` 实际上只是把 `prebuilt/${BR2_DIR}/*.so` 拷进 staging；没有 `.c`。真正的源码在 Amlogic 私有树里。改它只能改版本号 / prebuilt 内容。

##### `libplayer/` —— 播放核心（历史路径）
仅有 `Makefile`、`Config.in`、`libplayer.mk`。**`.gitignore` 把 `src/` 目录排除了**——某些 manifest 变体会单独 fetch src 填进来。不要以为是空仓。

##### `libdvr/` —— DVR / 录制 / 时移
DVB 录制、时移、流管理的专用库。有 `Android.mk` 和 `Android.bp`，Yocto 走 `Makefile`；`dummy_fe/` 是 frontend 的占位实现。

##### `cas-hal/` —— CAS HAL 框架
`libamcas`（核心）+ `liblinuxdvb_port`（Linux DVB 桥接）+ `libcJSON`（配置解析）+ `amlogic/`（Amlogic 私有实现）+ `cas_hal_test/`；对上提供 CAS 统一接口，对下对接各家 CA 供应商（Nagra/Irdeto/Verimatrix/NDS）。

##### `libmediadrm/` —— DRM 加载框架
以二进制插件形式挂载：`clearkey-bin`、`cleartvp-bin`、`drmplayer-bin`、`libsecmem-bin`、`libwfd_hdcp-bin`、`netflix_ta-bin`、`playready-bin`、`widevine-bin`、`wlcdmi-bin`、`youtubesign-bin`。所有 `.so`/`.ta` 均为预编译。

#### B. GStreamer 插件层

按命名空间分四族，不要混：

| 子目录 | 类型 | 职责 |
|--------|------|------|
| `gst-aml-drm-plugins1` | 基础设施 | GStreamer 层的 DRM 插件 |
| `gst-aml-drmbufferpool1` | 基础设施 | DMA-BUF / secure buffer pool |
| `gst-aml-utils` | 基础设施 | Amlogic GStreamer 公共工具 |
| `gst-plugin-aml-asink` | 1.x 插件 | Audio sink（驱 ALSA / 音频 HAL） |
| `gst-plugin-aml-demux` | 1.x 插件 | 自带 `aml-hwdemux` / `aml-qtdemux` / `aml-tsdemux` 三个子 demux |
| `gst-plugin-aml-picsink` | 1.x 插件 | 静态图像 sink |
| `gst-plugin-aml-subtitlesink` | 1.x 插件 | 字幕 sink |
| `gst-plugin-aml-v4l2dec` | 1.x 插件 | V4L2 stateful decoder（**同时带 autotools 和 meson**，recipe 里选其一） |
| `gst-plugin-aml-wlcdmi` | 1.x 插件 | Widevine L1 CDM 接口（meson 构建） |
| `gst-plugin-venc` | 通用命名 | 视频编码器插件 |
| `gst-plugin-video-sink` | 通用命名 | 视频 sink |
| `gst-fluendo-mpegdemux` | 通用命名 | Fluendo 开源 MPEG demux |
| `gst-app` | 应用 | GStreamer 应用包装 |
| `gst_agmplayer` | 应用 | Amlogic GStreamer 高级播放器 + `agmplayer.service`（systemd 单元） |

三个 GStreamer 插件的 bitbake recipe 散布在 `meta-meson/recipes-multimedia/`：`gst-aml-plugins`、`gst-aml-utils`、`gst-app`、`gst-plugin-venc`、`gstreamer`。

#### C. 渲染 / 同步层

| 组件 | 职责 |
|------|------|
| `libvideorender/` | 视频 render 库，内含 `drm/` / `mesonvideocompositor/` / `videotunnel/` / `westeros/` / `weston/` 多套后端适配。暴露 `render_common.h` / `render_plugin.h` |
| `avsync-lib/` | 音视频 PTS 同步库；`version_config.sh` 在配置时产生版本头 |

#### D. 音频 HAL 栈

##### `aml_audio_hal/` —— 音频栈核心
这是最复杂、扇出最广的组件。子目录：

| 子目录 | 职责 |
|--------|------|
| `audio_hal/` | HAL 主实现：`alsa_manager`、`amlAudioMixer`、`aml_audio_ms12_render`（Dolby MS12 通路）、`aml_audio_nonms12_render`（非 MS12 通路）、`aml_audio_delay`、`aml_audio_ease`（淡入淡出）、`aml_audio_scaletempo`（变速）、`aml_audio_spdifout`、`aml_audio_command_worker`（命令队列）、`aml_audio_avsync_table` 等 |
| `audio_codec/libdts`、`libdcv`、`libmpegh`、`libvorbis` | **HAL 自己内含的** 子 codec lib（注意：与顶层 `dts_release` / `libopus` 等并不是同一样东西） |
| `audio_client/` | 客户端侧调用接口 |
| `decoder/` / `encoder/` / `input/` | 解 / 编 / 采集通路 |
| `dtv_audio_utils/` | DTV 场景专用 |
| `vendor_process/` | OEM 后处理 hook |
| `utils/` / `projects/` | 工具 & 项目配置 |
| `version_config.sh` | **configure 阶段跑**，产生版本头；跳过 configure 会使版本不同步 |

`aml-audio-hal_git.bb` 同时打包了音频编解码填充 lib：`libfaad-aml`、`libmad-aml`、`libflac-aml`、`libadpcm-aml`、`libiamf-aml`、`libopus-aml`。默认启用集合由 `AUDIOHAL_SUPPORTED_CODECS="faad mad flac adpcm iamf opus"` 控制。

##### 其他音频组件

| 组件 | 职责 |
|------|------|
| `amaudio` | 对 `/dev/amaudio*` 等内核接口的用户态封装 |
| `hal_audio_service` | 音频 HAL 服务进程（有 `include/`、`src/`、`Makefile`） |
| `aml_alsa_plugins` | ALSA `ahal` PCM/CTL 插件（`aml_ahal.conf`、`pcm_ahal.c`、`ctl_ahal.c`） |
| `aml_amaudioutils` | 音频工具 |
| `audiocapture` | 音频采集 |
| `libaudioeffect` | 纯 `.so` 驱动的音效库：`libavl`、`libbalance`、`libdbx`、`libdpe`、`libeffectfactory`、`libhpeqwrapper`、`libtreblebasswrapper`、`libvirtualsurround`、`libvirtualx(4)` |
| `dolby_atmos_release` | Dolby Atmos 闭源解码（`src/` + `.mk`） |
| `dolby_ms12_release` | Dolby MS12 闭源（同上） |
| `dts_release` | DTS 闭源，`32bit/` + `64bit/` 二进制 + thin `Makefile`，视为密封 |

#### E. 编解码 / 格式 库

| 组件 | 说明 |
|------|------|
| `ffmpeg-aml/` | Amlogic fork FFmpeg，走 `meta-meson/recipes-multimedia/ffmpeg/ffmpeg_4.4.bb` |
| `ffmpeg_ctc/` | **另一个独立** FFmpeg fork，走**不同**的 recipe 路径；**千万不要把两者 patch 互相照搬** |
| `libfaad` | AAC（CMake + Makefile）|
| `libflac` | FLAC |
| `libmad` | MP3 |
| `libopus` | Opus |
| `libiamf` | IAMF（沉浸式音频），`code/` 是上游 submodule，**顶层是 Amlogic wrapper**，按层级改对级别 |
| `libadpcm` | ADPCM |

#### F. 辅助/跨层

| 组件 | 职责 |
|------|------|
| `secfirmload/` | 安全固件加载（TEE ta 的 `secloadbin/`） |
| `wifidisplay/` | Miracast Source（Display） |
| `v4l2-uvm-test/` | V4L2 + UVM（User-mode Video Memory）测试工具 |
| `mediasupport/` | 多媒体辅助 lib |
| `test_tool/` | 工具如 `spdif_in_dd_decoder` |
| `aml_iptv_firmware/` | IPTV 固件 blob（`prebuilt/`、`version.txt`） |

### 3.4 组件之间的相互关系（调用/依赖图）

```
应用 (Netflix, YouTube, DTVKit, aml-player-service)
  │  C++ API                          │ GStreamer pipeline
  ▼                                   ▼
aml_mp_sdk ──depends──► libplayer ─► libdvr (DVR)
     │                      │
     │                      ├─► mediahal-sdk (HAL 抽象)
     │                      │
     │                      ├─► cas-hal ────► libmediadrm (widevine/playready/...)
     │                      │                          │
     │                      └─► avsync-lib ─► libvideorender ─► DRM/Westeros/Weston
     │
     ├─► ffmpeg-aml (解复用/软解兜底)
     │
     └─► 音频通路
             │
             ▼
       aml_audio_hal ──► amaudio ──► /dev/amaudio* (kernel)
             │     ├──► dolby_ms12_release / dolby_atmos_release / dts_release
             │     ├──► libaudioeffect（LD_PRELOAD / dlopen 加载的 .so）
             │     ├──► hal_audio_service（进程化承载）
             │     └──► aml_alsa_plugins (ALSA ahal 挂 HAL 后端)
             │
             └──► libfaad/libmad/libflac/libopus/libiamf/libadpcm（被 HAL 选择性打包）

GStreamer 插件栈（另一条通路）：
  gst-fluendo-mpegdemux ┐
  gst-plugin-aml-demux  ┼─► gst-plugin-aml-v4l2dec ─► gst-plugin-aml-picsink
                        │                              └─► gst-plugin-aml-asink ─► aml_audio_hal
                        ├─► gst-aml-drm-plugins1 + gst-aml-drmbufferpool1
                        └─► gst-plugin-aml-subtitlesink + video-sink
  gst-aml-utils / gst-app 被以上插件公共依赖
  gst_agmplayer 把这些装到一个 service 里（agmplayer.service）

向下（kernel / 驱动）：
  - aml_audio_hal / amaudio → aml-comp/kernel/aml-*/sound/soc/amlogic
  - gst-plugin-aml-v4l2dec / libvideorender → aml-comp/hardware/aml-5.15/amlogic/media_modules（V4L2 编解码 kernel 模块）
  - gst-aml-drmbufferpool1 / libvideorender → DRM / libion (aml-comp/hardware/amlogic/libion)

与其他 aml-comp 子树的横向依赖：
  - libmediadrm + cas-hal  ←→ aml-comp/vendor/amlogic/{hdcp, tdk, provision}
  - secfirmload           ←→ aml-comp/vendor/amlogic/tdk（TEE/TA）
  - wifidisplay           ←→ aml-comp/hardware/wifi + 上层 Miracast HDCP
  - gst-plugin-aml-v4l2dec ←→ aml-comp/hardware/aml-5.15/amlogic/media_modules
```

### 3.5 构建系统对照表（易踩坑）

| 构建系统 | 组件 |
|---------|------|
| **CMake** | `aml_audio_hal`、`aml_mp_sdk`（也有 Makefile + Android.mk）、`libadpcm`、`libfaad`、`libflac`、`libmad`、`libopus` |
| **Plain Makefile**（多假定 Buildroot 风格 `TARGET_DIR` / `STAGING_DIR` / `PREFIX`） | `libvideorender`、`mediahal-sdk`、`libdvr`、`hal_audio_service`、`v4l2-uvm-test`、`avsync-lib`、`ffmpeg-aml`、`ffmpeg_ctc`、`cas-hal`、`libplayer`、`aml_alsa_plugins`、`aml_amaudioutils`、`libaudioeffect`、`dts_release` |
| **Autotools**（`configure.ac` + `autogen.sh`） | `gst-plugin-aml-asink`、`gst-plugin-aml-demux`、`gst-plugin-aml-picsink`、`gst-plugin-aml-subtitlesink`、`gst-plugin-aml-v4l2dec`（autotools 和 meson 并存）、`gst-plugin-video-sink`、`gst_agmplayer` |
| **Meson** | `gst-plugin-aml-v4l2dec`（另一份）、`gst-plugin-aml-wlcdmi` |
| **Android.mk only**（Yocto 不用，但不能删） | `aml_mp_sdk`、`cas-hal`、`ffmpeg_ctc`、`libdvr` 等 |

**跨构建系统并存时，BitBake 选哪个要看对应 `.bb`：`inherit cmake` vs 自定义 `EXTRA_OEMAKE`。** 另一套通常留给非 Yocto 下游，不能删也不能坏。

### 3.6 配置时（configure 阶段）副作用

这些组件的 configure 本身会"生成源文件"，跳过 configure 或手改源码不重 configure 会导致头不同步：

- `aml_audio_hal/CMakeLists.txt` 通过 `execute_process` 调 `sh version_config.sh ${AML_BUILD_DIR}` 产 version 头。
- `gst-plugin-aml-asink/configure.ac` 若无 `src/aml_version.h` 则从 `src/aml_version.h.in` 产生。
- `avsync-lib` / `libvideorender` 都有 `aml_version.h.in` + `version_config.sh`。

### 3.7 遗留 Buildroot 产物（看到请忽略）

顶层 `Config.in`、`multimedia.mk` 以及 `<组件>/*.mk`（`amaudio.mk`、`libplayer.mk`、`avsync-lib.mk`、`dolby_ms12_release.mk`、`wifidisplay.mk` 等）都是**前一版 Buildroot 移植的遗留**——Yocto/BitBake 不用。`Config.in` 里甚至引了已不存在的目录（`alsa-plugins`、`gst-aml-plugins`、`aml_halaudio`）。别依赖它们，也别修它们，别新增。**真正权威的构建元数据在 `meta-meson/recipes-multimedia/`**。

### 3.8 Recipe ↔ 源码的映射规律

- 大多数是"目录下划线 → recipe 连字符"：`aml_audio_hal/` ↔ `aml-audio-hal_git.bb`，`aml_mp_sdk/` ↔ `aml-mp-sdk_git.bb`，`libdvr/` ↔ `aml-libdvr`，`mediahal-sdk/` ↔ `aml-mediahal-sdk`。
- 例外：`aml-audio-hal_git.bb` 顺带打包 `libfaad-aml` / `libmad-aml` / `libflac-aml` / `libadpcm-aml` / `libiamf-aml` / `libopus-aml`。
- `ffmpeg-aml` 和 `ffmpeg_ctc` 虽同名 FFmpeg，但走两条独立 recipe，绝对不能混合打 patch。
- GStreamer 命名空间分三档，对应三套 recipe：`gst-aml-utils`、`gst-aml-plugins`（含 `gst-plugin-aml-*`）、`gst-app` / `gst-plugin-venc`。

### 3.9 DISTRO_FEATURES 与 `multimedia/` 目录的关系

- 当 `aml-comp/multimedia/dolby_ms12_release` 不存在时，`aml-setenv.sh` 会自动从 DISTRO_FEATURES 摘掉 Dolby MS12。
- 当 `aml-comp/multimedia/dts_release` 不存在时，DTS 相关 feature 也会被摘。
- **Feature "消失"的首查方向永远是**：相关 `aml-comp/` 目录是否在 repo sync 结果里。

### 3.10 修改的影响面（Gotchas）

- 改 `aml_audio_hal/include/`、`aml_mp_sdk/include/Aml_MP/`、`mediahal-sdk/` 导出头 → **扇出很多 recipe**；必须 `bitbake -p` 查 RDEPENDS。
- `mediahal-sdk` 源实为 prebuilt 拷贝器，找 `.c` 找不到——别钻牛角尖。
- `aml_iptv_firmware` / `dts_release` 都是二进制 + thin Makefile 的 sealed drop，不要去"源码化"。
- `libplayer/src/` 被 `.gitignore`，manifest 变体决定它是否被独立 fetch 填入。
- `libiamf/code/` 是上游 submodule，`libiamf/` 顶层是 Amlogic wrapper——改对层级。

### 3.11 推荐迭代节奏

1. **最快**：单组件独立构建（参考 3.5 对号入座）。示例：
   - CMake: `cmake -S aml_mp_sdk -B build/aml_mp_sdk && cmake --build build/aml_mp_sdk`
   - `aml_audio_hal` 还需对齐 recipe 的 PACKAGECONFIG：`-DUSE_DTV=ON -DUSE_MSYNC=ON -DUSE_SC2=ON` 等。
   - Autotools: `./autogen.sh && ./configure --with-path=<OUT_DIR> && make`
   - Meson: `meson setup build/<dir> <src> && meson compile -C build/<dir>`
   - Plain Makefile: Buildroot 风格环境变量较繁，建议直接 bitbake 驱动。
2. **中等**：`bitbake <单个 recipe>`——这是**唯一**能验证 packaging/staging、DEPENDS/RDEPENDS、PACKAGECONFIG 接线正确性的方式。
3. **最慢**：`bitbake <image>`——只在验证跨组件交互（导出头变更影响 `aml_mp_sdk` + `gst-aml-plugins` + `libplayer`）或 DISTRO_FEATURE toggle 时使用。

### 3.12 提交风格（Gerrit）

- Subject 以功能域开头：`audio: ...`、`multimedia: ...`、`dvr: ...`、`gst: ...`，或票号 `PB3-187: ...` / `SWPL-xxxx: ...`。
- **保留 `Change-Id:` trailer**——Gerrit 靠它去重；rebase 时不要重新生成，除非真的当作新 review。
- rebase vendor 提交时保留原作者的 `Signed-off-by:`。

---

## 四、一张图看清整个 SDK 的装配链

```
                ┌────────────────────┐
                │ .repo/manifest.xml │
                └──────────┬─────────┘
                           │ repo sync
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
  ┌──────────┐      ┌────────────┐      ┌──────────┐
  │  poky/   │      │meta-* 上游 │      │ aml-comp │
  │(Yocto)   │      │(第三方)    │      │(闭源源码)│
  └────┬─────┘      └─────┬──────┘      └────┬─────┘
       │                  │                  │
       │                  │                  │ 被消费
       ▼                  ▼                  ▼
  ┌─────────────────────────────────────────────────┐
  │  meta-meson/recipes-*   (BSP 把闭源源码打包)    │
  │  meta-aml-cfg/conf/machine/*.conf  (板级)       │
  │  meta-aml-apps/recipes-*   (OTT 应用接入)       │
  └─────────────────────┬───────────────────────────┘
                        │ source meta-meson/aml-setenv.sh <machine>
                        ▼
             ┌──────────────────────┐
             │  build-<soc>/        │
             │  conf/local.conf     │ ← 自动生成
             │  conf/bblayers.conf  │ ← 自动生成
             │  conf/auto.conf      │ ← manifest 锁版本
             └──────────┬───────────┘
                        │ bitbake <target>
                        ▼
             ┌──────────────────────┐
             │ tmp/deploy/images/...│
             │   (固件、image)      │
             └──────────────────────┘
```

---

## 五、一句话总结

- **Yocto SDK** = 上游 poky + 上游 meta-* + **Amlogic 三层**（`meta-meson` BSP 做 recipe、`meta-aml-cfg` 选板子、`meta-aml-apps` 装 OTT）+ **闭源源码底座 `aml-comp/`**，由 `aml-setenv.sh` 根据 `aml-comp/` 的实际内容动态拼出 `DISTRO_FEATURES` 和 BBLAYERS。
- **`aml-comp/` 的七子树**各司其职：`hardware/` 驱动、`kernel/` 三棵内核、`multimedia/` 多媒体全栈、`prebuilt/` 二进制产物、`thirdparty/` 浏览器与显示、`uboot/` 全 boot 栈、`vendor/amlogic/` 平台服务。
- **`aml-comp/multimedia/` 是 Amlogic 的"codec + HAL + SDK + GStreamer 插件"全套源码**，自底向上装出 `编解码 lib → 音频 HAL → 渲染/同步 → 媒体中间件 → GStreamer 插件 / Aml_MP_SDK → 应用`五层流水线，由 `meta-meson/recipes-multimedia/` 做 Yocto 打包；每一层都可以独立 build 来加快迭代，只有 `bitbake <recipe>` 才能验证 staging 接线。
