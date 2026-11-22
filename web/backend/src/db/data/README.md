# 行政区划数据

`regions.json` 为 `seed.py` 使用的行政区划种子（按上级编码先于下级排序）。

## 来源与范围

- 覆盖全国 **31 个省级行政区、342 个地市、3,056 个区县、41,272 个街道/乡镇**，共 44,701 条。
- 本文件于 2026-11-22 由生产库 `regions` 表导出，与线上区划树一致。
- 基础数据源：[modood/Administrative-divisions-of-China](https://github.com/modood/Administrative-divisions-of-China)
  的 `dist/pcas-code.json`（WTFPL 许可），并合并了项目历史夹具。
- 浙江省保留项目既有夹具编码（与 `COMMUNITIES` 的街道编码对齐，如 `330106001` 文新街道）；
  这些编码与后续导入的全国数据存在重名/编码冲突，导出时按线上库现状原样保留。
- 编码已归一化为项目使用的 6 位省/市/区县编码（如 `11` → `110000`、`1101` → `110100`）；
  直辖市下辖乡镇及东莞/中山等不设区县的地市，区县节点编码为 9 位。
- 测试不直接灌入全量数据：`tests/conftest.py` 只取“全部省份 + 北京/陕西/杭州子树”，
  数据集本身的完整性由 `test_region_seed_dataset_is_complete_and_consistent` 校验。

## 维护

- 新增/修改区划时同步更新本文件；`seed.py` 的 `_sync_regions` 会按 `code` 幂等补齐/校正，
  已初始化的开发库无需清库即可在下一次启动时增量同步。
- **重新导入区划后必须递增** `web/frontend/src/api/index.ts` 中的
  `REGION_*_CACHE_KEY` 版本号（当前 `v3`）：管理端会把区划树缓存 12 小时，
  不递增会导致已打开过页面的浏览器继续使用旧树（症状：部分省份的地市/区县下拉框为空）。
- 街道级编码被小区档案的 `street_id` 引用；调整既有编码前需评估已绑定数据。
