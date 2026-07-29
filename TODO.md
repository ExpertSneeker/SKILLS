# Todo list

## temu-img
> temu-img Skill的功能实现

- [x] 读取产品拍摄图的时候只读取JPG/PNG, 不要读取相机raw源格式, 比如.ARW,.CR2等等.
- [x] 最小改动实现:
    - [x] 除了明确定义为"定制模板"的图片外, 所有出现的色块都不要出现颜色编号
    - [x] 主图上面如果要求添加色块，色块必须直接加在背景图(场景图)上面，色块与背景之间不要加底色。并且主图上的配色图不要加颜色编号或颜色名字
- [x] 完整读取 豆包Seedream-5.0 Pro 的生图原理/流程和规范：https://console.volcengine.com/ark/region:cn-beijing/docs/82379/2582774
    - [x] 最小改动实现接入 Seedream-5.0-Pro API 生图功能，编写references/seedream.md
    - [x] 在SKILL.md中的生图工具选择器中加入seedream.md的路径/别名与相关简单介绍
- [x] 最小改动优化Skill图片生成风格提示词中的文案字体/配色来源/版式等
- [ ] 增加针对定制产品的规范
    - [ ] 编写references/custom-product.md，编写关于定制模板/定制尺寸/系带/防滑底/滚边相关要求与参考
    - [ ] 在SKILL.md中要求判断产品为定制产品则读取custom-product.md