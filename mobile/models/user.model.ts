export type AuthStatus =
  | 'NOT_LOGIN'
  | 'LOGGED_IN_UNVERIFIED'
  | 'VERIFYING'
  | 'VERIFIED_UNOWNER'
  | 'REJECTED'
  | 'SUBMITTING_PROOF'
  | 'PENDING_AUDIT'
  | 'VERIFIED_OWNER'
  | 'FROZEN'

export type CertificationState =
  | 'UNVERIFIED'
  | 'PENDING'
  | 'VERIFIED'
  | 'REJECTED'
  | 'SUPPLEMENT'
  | 'FROZEN'
  | 'REVOKED'

export interface CertificationStatus {
  status: CertificationState
  rejectReason: string
  canResubmit: boolean
  submittedAt: number
  certId: string
  communityId?: string
  communityName?: string
}

/** 注册新人引导状态：NEW → PROFILE_COMPLETED → COMPLETED。 */
export type OnboardingStatus = 'NEW' | 'PROFILE_COMPLETED' | 'COMPLETED'

export type LoginIntent = 'login' | 'register'

export interface UserProfile {
  id: string
  nickname: string
  phone: string
  email: string
  address: string
  bio: string
  avatarPreset: string
  avatarDataUrl: string
  showBio: boolean
  shareAddressAfterOrder: boolean
  verified: boolean
  realnameVerified?: boolean
  ownerVerified?: boolean
  realnameStatus?: CertificationState
  ownerStatus?: CertificationState
  creditScore: number
  creditLevel: string
  dealCount: number
  communityName: string
  joinedDays: number
  authStatus: AuthStatus
  /** 旧版本缓存可能没有该字段，缺省视为 COMPLETED。 */
  onboardingStatus?: OnboardingStatus
  intentCommunityId?: string
  intentCommunityName?: string
}

export interface LoginResult {
  accessToken: string
  refreshToken: string
  profile: UserProfile
  isNewUser: boolean
  onboardingStatus?: OnboardingStatus
}

export interface SmsCodeResult {
  cooldown: number
  mockCode?: string
}

export interface LoginSmsOptions {
  intent?: LoginIntent
  agreed?: boolean
  agreementVersion?: string
  privacyVersion?: string
}

export interface RegisterCompletePayload {
  nickname?: string
  avatarKey?: string
  /** 真实后端为数字 ID；Mock 小区 ID 为字符串，兼容两种形态。 */
  intentCommunityId?: number | string
  skip?: boolean
  finish?: boolean
}

export interface AuthStatusResult {
  status: AuthStatus
  realname?: CertificationStatus
  owner?: CertificationStatus
  realnameVerified: boolean
  ownerVerified: boolean
  rejectReason?: string
  rejectType?: 'REALNAME' | 'OWNER_PROOF' | ''
  canResubmit?: boolean
}

export interface RealnamePayload {
  frontImage: string
  backImage: string
  faceToken: string
}

export interface OwnerProofPayload {
  communityId: string
  identity: 'owner' | 'tenant' | 'family'
  images: string[]
}
