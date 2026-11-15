import * as authApi from '../api/auth.api'
import { ApiError } from '../api/errors'
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
import { isPhone, isSmsCode } from '../utils/validator'

export const authService = {
  async sendSmsCode(phone: string): Promise<SmsCodeResult> {
    if (!isPhone(phone)) throw new ApiError(40001, '请输入正确的手机号')
    return authApi.sendSmsCode(phone.trim())
  },

  async loginBySms(phone: string, code: string, options: LoginSmsOptions = {}): Promise<LoginResult> {
    if (!isPhone(phone)) throw new ApiError(40001, '请输入正确的手机号')
    if (!isSmsCode(code)) throw new ApiError(40001, '请输入 6 位验证码')
    return authApi.loginBySms(phone.trim(), code.trim(), options)
  },

  completeRegistration(payload: RegisterCompletePayload): Promise<UserProfile> {
    return authApi.completeRegistration(payload)
  },

  loginByOneClick(token: string): Promise<LoginResult> {
    return authApi.loginByOneClick(token)
  },

  loginByWechat(code: string): Promise<LoginResult> {
    return authApi.loginByWechat(code)
  },

  getStatus(): Promise<AuthStatusResult> {
    return authApi.getAuthStatus()
  },

  submitRealname(payload: RealnamePayload): Promise<{ status: string; message: string }> {
    return authApi.submitRealname(payload)
  },

  submitOwnerProof(payload: OwnerProofPayload): Promise<{ status: string; auditHours: number }> {
    return authApi.submitOwnerProof(payload)
  },

  logout(): Promise<{ success: boolean }> {
    return authApi.logoutApi()
  },
}
