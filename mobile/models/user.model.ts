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
  creditScore: number
  creditLevel: string
  dealCount: number
  communityName: string
  joinedDays: number
  authStatus: AuthStatus
}

export interface LoginResult {
  accessToken: string
  refreshToken: string
  profile: UserProfile
  isNewUser: boolean
}

export interface SmsCodeResult {
  cooldown: number
  mockCode?: string
}

export interface AuthStatusResult {
  status: AuthStatus
  realnameVerified: boolean
  ownerVerified: boolean
  rejectReason?: string
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
