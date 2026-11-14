export interface AppSettings {
  pushEnabled: boolean
  tradeNotifyEnabled: boolean
  communityNotifyEnabled: boolean
  elderMode: boolean
  theme: 'light'
  showBio: boolean
  shareAddressAfterOrder: boolean
}

export interface AppConfig {
  nearbyRadiusKm: number
  maxCommunities: number
  maxItemImages: number
  minItemImages: number
  maxLifeImages: number
  maxVideoSeconds: number
  payTimeoutMinutes: number
  appointmentAutoCancelHours: number
  supportPhone: string
}

export interface HomeBundle {
  community: import('./community.model').CommunitySummary
  zones: import('./item.model').ZoneStat[]
  broadcasts: import('./notification.model').Broadcast[]
  hotItems: import('./item.model').Item[]
  serviceHelp: import('./service.model').ServicePost[]
  serviceOffer: import('./service.model').ServicePost[]
  lifePosts: import('./life.model').LifePost[]
  notificationUnread: number
}
