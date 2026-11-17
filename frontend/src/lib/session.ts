/** 与后端 calendar.in_continuous_auction 对齐：工作日连续竞价。 */

function nowShanghai(): Date {
  return new Date(new Date().toLocaleString('en-US', { timeZone: 'Asia/Shanghai' }))
}

function minutesOfDay(d: Date): number {
  return d.getHours() * 60 + d.getMinutes()
}

export function inContinuousAuction(at: Date = nowShanghai()): boolean {
  const day = at.getDay() // 0=Sun
  if (day === 0 || day === 6) return false
  const m = minutesOfDay(at)
  const morning = m >= 9 * 60 + 30 && m <= 11 * 60 + 30
  const afternoon = m >= 13 * 60 && m <= 15 * 60
  return morning || afternoon
}
