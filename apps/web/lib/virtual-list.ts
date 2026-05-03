export type VirtualWindow = {
  start: number;
  end: number;
  offsetTop: number;
  totalHeight: number;
};

export function computeVirtualWindow(
  totalCount: number,
  scrollTop: number,
  rowHeight: number,
  viewportHeight: number,
  overscan: number = 4,
): VirtualWindow {
  const safeCount = Math.max(0, totalCount);
  const safeRowHeight = Math.max(1, rowHeight);
  const safeViewport = Math.max(1, viewportHeight);
  const safeScrollTop = Math.max(0, scrollTop);
  const safeOverscan = Math.max(0, overscan);

  if (safeCount === 0) {
    return {
      start: 0,
      end: 0,
      offsetTop: 0,
      totalHeight: 0,
    };
  }

  const visibleCount = Math.ceil(safeViewport / safeRowHeight);
  const rawStart = Math.floor(safeScrollTop / safeRowHeight) - safeOverscan;
  const start = Math.max(0, rawStart);
  const end = Math.min(safeCount, start + visibleCount + safeOverscan * 2);
  return {
    start,
    end,
    offsetTop: start * safeRowHeight,
    totalHeight: safeCount * safeRowHeight,
  };
}
