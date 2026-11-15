# 行政区划数据

`regions.json` 为 `seed.py` 使用的行政区划种子（按上级编码先于下级排序）。

## 来源与范围

- 数据源：[modood/Administrative-divisions-of-China](https://github.com/modood/Administrative-divisions-of-China)
  的 `dist/pcas-code.json`（最后更新 2023-09-13，WTFPL 许可）。
- 覆盖 **31 个省级行政区**（省、自治区、直辖市）。
- 浙江省保留项目既有夹具编码（与 `COMMUNITIES` 的街道编码对齐）。
- 北京市、陕西省完整下钻到街道/镇/乡；其余省级行政区本期仅保留省级节点。
- 编码已归一化为项目使用的 6 位省/市编码（如 `11` → `110000`、`1101` → `110100`）。

## 维护

- 新增/修改区划时同步更新本文件；`seed.py` 的 `_sync_regions` 会按 `code` 幂等补齐/校正，
  已初始化的开发库无需清库即可在下一次启动时增量同步。
- 街道级编码被小区档案的 `street_id` 引用；调整既有编码前需评估已绑定数据。
