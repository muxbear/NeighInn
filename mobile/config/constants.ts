import type { TradeType, ZoneKey } from '../models/item.model'

export interface ZoneConfig {
  key: ZoneKey
  name: string
  label: string
  icon: string
  tone: 'gift' | 'swap' | 'sale' | 'service'
  title: string
  subtitle: string
  description: string
}

export const ZONES: ZoneConfig[] = [
  {
    key: 'gift',
    name: '物品赠与',
    label: '免费领取',
    icon: 'gift',
    tone: 'gift',
    title: '阳光花园 · 认证业主专属',
    subtitle: '让闲置找到新主人，让善意在邻里间流动',
    description: '让闲置找到新主人，好物免费送给邻居',
  },
  {
    key: 'swap',
    name: '物品交换',
    label: '以物换物',
    icon: 'swap',
    tone: 'swap',
    title: '阳光花园 · 互换专区',
    subtitle: '用你的闲置，换一件真正需要的物品',
    description: '以物换物，各取所需，让闲置继续流动',
  },
  {
    key: 'sale',
    name: '闲置赚米',
    label: '担保交易',
    icon: 'wallet',
    tone: 'sale',
    title: '阳光花园 · 闲置出售',
    subtitle: '平台担保支付，线下验货满意再放款',
    description: '同小区当面验货，平台担保支付更安心',
  },
  {
    key: 'service',
    name: '服务互助',
    label: '邻里帮忙',
    icon: 'friend',
    tone: 'service',
    title: '阳光花园 · 服务互助',
    subtitle: '接送、照看、陪伴，需要时邻居就在身边',
    description: '邻里互助、陪伴与共享服务都在这里',
  },
]

export const ZONE_MAP: Record<ZoneKey, ZoneConfig> = ZONES.reduce((acc, zone) => {
  acc[zone.key] = zone
  return acc
}, {} as Record<ZoneKey, ZoneConfig>)

export const TRADE_TYPES: Array<{ value: TradeType; label: string; desc: string; icon: string }> = [
  { value: '出售', label: '出售', desc: '担保支付，验货后放款', icon: 'wallet' },
  { value: '免费', label: '免费', desc: '赠予邻居，免费领取', icon: 'gift' },
  { value: '互换', label: '互换', desc: '以物换物，各取所需', icon: 'swap' },
]

// 与统一服务端 /categories（SRS M02-01/M03-01）保持一致，避免发布时类目/成色校验失败。
export const ITEM_CATEGORIES = [
  '家具家电',
  '母婴用品',
  '数码',
  '图书',
  '服饰',
  '运动户外',
  '其他',
]

export const ITEM_CONDITIONS = ['全新', '九九新', '轻微使用痕迹', '明显使用痕迹', '有功能缺陷']

export const LIFE_CATEGORIES = ['全部', '小区风景', '邻里日常', '个人风采', '萌宠生活'] as const

export const SERVICE_CATEGORIES = ['全部', '接送照看', '宠物照看', '学习陪伴', '邻里活动', '维修安装', '其他'] as const

export const SERVICE_KINDS = ['求助', '提供'] as const

export const SORT_OPTIONS = ['最新发布', '离我最近', '价格从低到高'] as const

export const PAY_METHODS = [
  { key: 'wechat', label: '微信支付', icon: 'wechat', desc: '推荐使用' },
  { key: 'alipay', label: '支付宝', icon: 'wallet', desc: '安全便捷' },
] as const

export const REVIEW_TAGS = [
  '交易愉快',
  '物品真实',
  '沟通顺畅',
  '准时赴约',
  '图片与实物一致',
  '态度好',
]

export const DISPUTE_REASONS = [
  '物品与描述不符',
  '物品存在质量问题',
  '卖家未按约定时间赴约',
  '卖家拒绝交付',
  '其他原因',
]

export const INSPECT_FAIL_REASONS = [
  '物品与描述严重不符',
  '物品存在明显损坏',
  '物品无法正常使用',
  '卖方要求临时加价',
  '其他原因',
]

export const REPORT_REASONS = [
  '虚假宣传',
  '违禁物品',
  '骚扰谩骂',
  '涉嫌诈骗',
  '侵犯隐私',
  '其他',
]

export const IDENTITY_OPTIONS = [
  { key: 'owner', label: '业主', desc: '房产证 / 购房合同' },
  { key: 'tenant', label: '租户', desc: '租赁合同 / 缴费记录' },
  { key: 'family', label: '家属', desc: '户口本 / 亲属关系证明' },
] as const

export const AVATAR_PRESET_LABELS: Record<string, string> = {
  'avatar-person-1': '元气女孩',
  'avatar-person-2': '眼镜男孩',
  'avatar-person-3': '棒球少年',
  'avatar-animal-1': '橘猫',
  'avatar-animal-2': '柴犬',
  'avatar-animal-3': '白兔',
  'avatar-landmark-1': '长城云海',
  'avatar-landmark-2': '秋日长城',
  'avatar-landmark-3': '古城远眺',
  'avatar-nature-1': '雪山湖泊',
  'avatar-nature-2': '森林静湖',
  'avatar-nature-3': '湖畔绿意',
}

export const AVATAR_CATEGORIES = [
  { key: 'person', label: '卡通人物', prefix: 'avatar-person' },
  { key: 'animal', label: '卡通动物', prefix: 'avatar-animal' },
  { key: 'landmark', label: '名胜古迹', prefix: 'avatar-landmark' },
  { key: 'nature', label: '自然风景', prefix: 'avatar-nature' },
] as const

/** 协议版本默认值：实际以 /config/app 下发的管理端参数为准，这里是离线兜底。 */
export const AGREEMENT_VERSION = '2026-11-01'
export const PRIVACY_VERSION = '2026-11-01'

export const STORAGE_KEYS = {
  accessToken: 'ni_token_access',
  refreshToken: 'ni_token_refresh',
  userProfile: 'ni_user_profile',
  settings: 'ni_settings',
  draftItem: 'ni_draft_item',
  draftLife: 'ni_draft_life',
  searchHistory: 'ni_search_history',
  viewHistory: 'ni_view_history',
  homeFeed: 'ni_home_feed',
  conversations: 'ni_im_conversations',
  trackQueue: 'ni_track_queue',
  mockSession: 'ni_mock_session',
  certGuideDismissedAt: 'ni_cert_guide_dismissed_at',
} as const

export const ERROR_MESSAGES: Record<number, string> = {
  40001: '参数校验失败，请检查后重试',
  40101: '登录已失效，请重新登录',
  40301: '当前账号没有操作权限',
  40302: '请先完成实名 / 业主认证',
  40901: '物品已被预约，看看其他好物吧',
  42201: 'AI 质检未通过，请修改后重新提交',
  42901: '操作太频繁，请稍后再试',
  50000: '系统开小差了，请稍后重试',
}

export const TRADE_METHOD_LABEL: Record<TradeType, string> = {
  出售: '担保支付',
  免费: '免费领取',
  互换: '发起互换',
}

export const TRADE_METHOD_BUTTON: Record<TradeType, { text: string; icon: string; tone: string }> = {
  出售: { text: '担保支付购买', icon: 'shield', tone: 'sale' },
  免费: { text: '申请免费领取', icon: 'gift', tone: 'gift' },
  互换: { text: '发起物品互换', icon: 'swap', tone: 'swap' },
}

export const NOTIFICATION_CATEGORIES = ['全部', '交易', '互动', '社区'] as const

export const ORDER_CATEGORIES = [
  { key: 'free', label: '免费订单', icon: 'gift', tradeType: '免费' as TradeType },
  { key: 'swap', label: '互换订单', icon: 'swap', tradeType: '互换' as TradeType },
  { key: 'monetary', label: '货币订单', icon: 'wallet', tradeType: '出售' as TradeType },
] as const

export const ELDER_SCALE = 2
