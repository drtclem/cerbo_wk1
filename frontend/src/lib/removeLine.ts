/** Patient line-removal UI helpers. No money math. */

export const REMOVED_BY_PATIENT_LABEL = "Removed by patient";

export type RemovableLine = {
  id: number;
  removed_at: string | null;
};

/** Line id awaiting an inline "Are you sure?" confirm, or null when idle. */
export type RemoveConfirmState = number | null;

export function activeLines<T extends RemovableLine>(lines: readonly T[]): T[] {
  return lines.filter((line) => line.removed_at === null);
}

export function removedLines<T extends RemovableLine>(lines: readonly T[]): T[] {
  return lines.filter((line) => line.removed_at !== null);
}

export function lineStruckThrough(line: RemovableLine): boolean {
  return line.removed_at !== null;
}

export function beginRemoveConfirm(
  _current: RemoveConfirmState,
  lineId: number,
): RemoveConfirmState {
  return lineId;
}

export function cancelRemoveConfirm(): RemoveConfirmState {
  return null;
}

export function confirmingLineId(state: RemoveConfirmState): number | null {
  return state;
}

export function isRemoveConfirming(state: RemoveConfirmState, lineId: number): boolean {
  return state === lineId;
}
