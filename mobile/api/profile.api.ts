import type { AvatarPresetGroup, UserProfile } from '../models'
import { get, post, put } from './request'

export function getProfile(): Promise<UserProfile> {
  return get<UserProfile>('/users/me')
}

export function updateProfile(payload: Partial<UserProfile>): Promise<UserProfile> {
  return put<UserProfile>('/users/me', payload as Record<string, any>, { loading: true })
}

export function updateAvatar(payload: { avatarPreset?: string; avatarDataUrl?: string }): Promise<UserProfile> {
  return post<UserProfile>('/users/me/avatar', payload, { loading: true })
}

export function getAvatarPresets(): Promise<AvatarPresetGroup[]> {
  return get<AvatarPresetGroup[]>('/avatars/presets')
}
