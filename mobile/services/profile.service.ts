import * as profileApi from '../api/profile.api'
import type { AvatarPresetGroup, UserProfile } from '../models'

export const profileService = {
  getProfile(): Promise<UserProfile> {
    return profileApi.getProfile()
  },

  updateProfile(payload: Partial<UserProfile>): Promise<UserProfile> {
    return profileApi.updateProfile(payload)
  },

  updateAvatar(payload: { avatarPreset?: string; avatarDataUrl?: string }): Promise<UserProfile> {
    return profileApi.updateAvatar(payload)
  },

  getAvatarPresets(): Promise<AvatarPresetGroup[]> {
    return profileApi.getAvatarPresets()
  },
}
