import { getItemDistance } from '../api/item.api'
import type { DistanceInfo } from '../models'
import { formatDistance, formatTravelTime } from '../utils/formatter'

/**
 * 距离与耗时全部由服务端计算，端侧只做展示；
 * 定位仅用于“附近”排序，不直接调用地图 API。
 */
export const mapService = {
  getDistance(itemId: string): Promise<DistanceInfo> {
    return getItemDistance(itemId)
  },

  buildPanel(meters: number): { distance: string; walk: string; bike: string; car: string } {
    return {
      distance: formatDistance(meters),
      walk: `步行${formatTravelTime(meters, 'walk')}`,
      bike: `骑行${formatTravelTime(meters, 'bike')}`,
      car: `驾车${formatTravelTime(meters, 'car')}`,
    }
  },
}
