# 知识世界三维资产

本目录的清单随生产构建托管在 `/world-art/threejs/manifest.json`。实际模型由现有 React 工程中的 Three.js 程序建模代码生成，并随生产 JavaScript 分包加载；这里没有只在 Vite 开发模式存在的绝对文件路径或远程模型依赖。

本轮新增的营地、单位、敌人、据点、休息房间、像素纹理及演出几何均为项目自制。Tiny Glade、Octopia、CozySpace 只用于风格参考，没有提取或复制其商业资源。未使用收费图片/视频生成服务。项目自制内容的使用与项目代码保持一致，本文件不额外授予第三方商业素材许可。

建模依赖 Three.js 的基础几何、RoundedBoxGeometry 与 BufferGeometryUtils，使用其 MIT 许可；原文见同目录 `three-LICENSE.txt`。原应用字体的 OFL 原文仍在 `/licenses/`。

美术程序不决定积分、所有权、成长等级、战斗结果或休闲时长。测试/目录预览有明确标识；生产场景只读取实际对象和正式回执。

几何审计、生产托管、环绕截图、连续录屏和性能证据分别记录于 `artifacts/art/system-core/`；实际状态以 `docs/art/实施记录.md` 为准。清单列出模型存在，不等同于全部 SC 验收通过。
