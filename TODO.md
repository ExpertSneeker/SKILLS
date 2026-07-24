# Todo list

## temu-img
> temu-img Skill的功能实现

- [x] 读取产品拍摄图的时候只读取JPG/PNG, 不要读取相机raw源格式, 比如.ARW,.CR2等等.
- [x] 最小改动实现:
    - [x] 除了明确定义为"定制模板"的图片外, 所有出现的色块都不要出现颜色编号
    - [x] 主图上面如果要求添加色块，色块必须直接加在背景图(场景图)上面，色块与背景之间不要加底色。并且主图上的配色图不要加颜色编号或颜色名字
- [ ] 完整读取 $Lovart-API 的生图原理/流程和规范，同时参考Github的说明：https://github.com/lovartai/lovart-skill/tree/main
    - [ ] 最小代码实现接入Lovart-api生图功能，可指定生图模型，编写references/lovart-api.md
    - [ ] 在SKILL.md中的生图工具选择器中假如lovart-api.md的路径与相关简单介绍
