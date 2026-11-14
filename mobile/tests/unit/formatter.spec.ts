import { describe, expect, it } from 'vitest'
import {
  formatAmount,
  formatCount,
  formatCountdown,
  formatDays,
  formatDistance,
  formatPrice,
  formatRelativeTime,
  formatThousands,
  formatTravelTime,
} from '../../utils/formatter'

describe('formatter', () => {
  it('formats price with and without symbol', () => {
    expect(formatPrice(128)).toBe('¥128')
    expect(formatPrice('128.5')).toBe('¥128.50')
    expect(formatPrice(0)).toBe('¥0')
    expect(formatPrice('abc')).toBe('¥0')
    expect(formatPrice(128, false)).toBe('128')
  })

  it('formats amount with fixed decimals', () => {
    expect(formatAmount(128)).toBe('128.00')
    expect(formatAmount('12.5')).toBe('12.50')
    expect(formatAmount('bad')).toBe('0.00')
  })

  it('formats distance at 10m granularity', () => {
    expect(formatDistance(8)).toBe('约 8m')
    expect(formatDistance(284)).toBe('约 280m')
    expect(formatDistance(1234)).toBe('约 1.2km')
    expect(formatDistance(-1)).toBe('距离未知')
  })

  it('formats travel time', () => {
    expect(formatTravelTime(72, 'walk')).toBe('1分钟')
    expect(formatTravelTime(1440, 'walk')).toBe('20分钟')
    expect(formatTravelTime(1200, 'bike')).toBe('5分钟')
    expect(formatTravelTime(14400, 'car')).toBe('20分钟')
  })

  it('formats relative time', () => {
    const now = 1_700_000_000_000
    expect(formatRelativeTime(now - 10_000, now)).toBe('刚刚')
    expect(formatRelativeTime(now - 18 * 60_000, now)).toBe('18分钟前')
    expect(formatRelativeTime(now - 3 * 3_600_000, now)).toBe('3小时前')
    expect(formatRelativeTime(now - 26 * 3_600_000, now)).toBe('昨天')
  })

  it('formats counts', () => {
    expect(formatCount(9999)).toBe('9999')
    expect(formatCount(12000)).toBe('1.2万')
    expect(formatCount(10000)).toBe('1万')
  })

  it('formats countdown', () => {
    expect(formatCountdown(30 * 60_000)).toBe('30:00')
    expect(formatCountdown(65_000)).toBe('01:05')
    expect(formatCountdown(-1)).toBe('00:00')
  })

  it('formats days and thousands', () => {
    expect(formatDays(28)).toBe('28天')
    expect(formatDays(60)).toBe('2个月')
    expect(formatDays(730)).toBe('2年')
    expect(formatThousands(2138)).toBe('2,138')
  })
})
