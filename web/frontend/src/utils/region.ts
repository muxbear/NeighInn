export interface RegionNode {
  id: string
  name: string
  level: string
  code?: string
  childCount?: number
  children?: RegionNode[]
}

export interface RegionEntry {
  node: RegionNode
  parentId: string | null
  /** 从省级到直接父级的节点链（不含自身）。 */
  ancestors: RegionNode[]
}

/** 省级节点分组顺序，与社区运维左侧行政区划树保持一致。 */
export const PROVINCE_GROUP_ORDER = ['直辖市', '省份', '自治区'] as const

const MUNICIPALITIES = ['北京市', '天津市', '上海市', '重庆市']

const PROVINCE_PINYIN: Record<string, string> = {
  北京市: 'beijing', 天津市: 'tianjin', 河北省: 'hebei', 山西省: 'shanxi',
  内蒙古自治区: 'neimenggu', 辽宁省: 'liaoning', 吉林省: 'jilin',
  黑龙江省: 'heilongjiang', 上海市: 'shanghai', 江苏省: 'jiangsu',
  浙江省: 'zhejiang', 安徽省: 'anhui', 福建省: 'fujian', 江西省: 'jiangxi',
  山东省: 'shandong', 河南省: 'henan', 湖北省: 'hubei', 湖南省: 'hunan',
  广东省: 'guangdong', 广西壮族自治区: 'guangxi', 海南省: 'hainan',
  重庆市: 'chongqing', 四川省: 'sichuan', 贵州省: 'guizhou', 云南省: 'yunnan',
  西藏自治区: 'xizang', 陕西省: 'shaanxi', 甘肃省: 'gansu', 青海省: 'qinghai',
  宁夏回族自治区: 'ningxia', 新疆维吾尔自治区: 'xinjiang',
}

function provinceCategory(name: string): string {
  if (MUNICIPALITIES.includes(name)) return '直辖市'
  if (name.endsWith('自治区')) return '自治区'
  return '省份'
}

function provincePinyin(name: string): string {
  return PROVINCE_PINYIN[name] || name
}

/** 将省级节点按直辖市 / 省份 / 自治区分组，组内按拼音排序。 */
export function groupProvinces(provinces: RegionNode[]): { label: string; provinces: RegionNode[] }[] {
  const buckets: Record<string, RegionNode[]> = { 直辖市: [], 省份: [], 自治区: [] }
  for (const province of provinces) {
    const category = provinceCategory(province.name)
    if (!buckets[category]) buckets[category] = []
    buckets[category].push(province)
  }
  return PROVINCE_GROUP_ORDER
    .map((label) => ({
      label,
      provinces: (buckets[label] || [])
        .slice()
        .sort((a, b) => provincePinyin(a.name).localeCompare(provincePinyin(b.name))),
    }))
    .filter((group) => group.provinces.length > 0)
}

/** 将行政区划树展开为 id -> 节点 / 父级 / 祖先链 的索引，便于按社区反查完整路径。 */
export function indexRegions(roots: RegionNode[]): Record<string, RegionEntry> {
  const index: Record<string, RegionEntry> = {}
  const walk = (nodes: RegionNode[], parentId: string | null, ancestors: RegionNode[]) => {
    for (const node of nodes) {
      index[String(node.id)] = { node, parentId, ancestors }
      if (node.children?.length) {
        walk(node.children, String(node.id), [...ancestors, node])
      }
    }
  }
  walk(roots, null, [])
  return index
}
