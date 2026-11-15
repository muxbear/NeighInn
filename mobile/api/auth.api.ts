import type {
  AuthStatusResult,
  LoginResult,
  LoginSmsOptions,
  OwnerProofPayload,
  RealnamePayload,
  RegisterCompletePayload,
  SmsCodeResult,
  UserProfile,
} from '../models'
import { get, post } from './request'

export function sendSmsCode(phone: string): Promise<SmsCodeResult> {
  return post<SmsCodeResult>('/auth/sms-code', { phone }, { auth: false, idempotent: false })
}

export function loginBySms(phone: string, code: string, options: LoginSmsOptions = {}): Promise<LoginResult> {
  return post<LoginResult>(
    '/auth/login/sms',
    {
      phone,
      code,
      intent: options.intent ?? 'login',
      agreed: options.agreed ?? false,
      agreementVersion: options.agreementVersion ?? '',
      privacyVersion: options.privacyVersion ?? '',
    },
    { auth: false },
  )
}

export function completeRegistration(payload: RegisterCompletePayload): Promise<UserProfile> {
  return post<UserProfile>('/auth/register/complete', payload as Record<string, any>, { loading: true })
}

export function loginByOneClick(token: string): Promise<LoginResult> {
  return post<LoginResult>('/auth/login/one-click', { carrierToken: token }, { auth: false })
}

export function loginByWechat(code: string): Promise<LoginResult> {
  return post<LoginResult>('/auth/login/wechat', { code }, { auth: false })
}

export function refreshTokenApi(refreshToken: string): Promise<{ accessToken: string; refreshToken: string }> {
  return post('/auth/token/refresh', { refreshToken }, { auth: false, idempotent: false })
}

export function getAuthStatus(): Promise<AuthStatusResult> {
  return get<AuthStatusResult>('/auth/status')
}

export function submitRealname(payload: RealnamePayload): Promise<{ status: string; message: string }> {
  return post('/auth/realname', payload, { loading: true })
}

export function submitOwnerProof(payload: OwnerProofPayload): Promise<{ status: string; auditHours: number }> {
  return post('/auth/owner-proof', payload, { loading: true })
}

export function logoutApi(): Promise<{ success: boolean }> {
  return post('/auth/logout', {}, { idempotent: false })
}
