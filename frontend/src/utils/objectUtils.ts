/**
 * Deeply compares two objects for equality
 * @param obj1 First object to compare
 * @param obj2 Second object to compare
 * @returns boolean indicating if objects are equal
 */
export function areObjectsEqual(obj1: any, obj2: any): boolean {
  if (obj1 === obj2) return true;
  if (obj1 == null || obj2 == null) return false;
  if (typeof obj1 !== 'object' || typeof obj2 !== 'object') return false;

  if (Array.isArray(obj1) && Array.isArray(obj2)) {
    if (obj1.length !== obj2.length) return false;
    return obj1.every((val, idx) => areObjectsEqual(val, obj2[idx]));
  }

  if (obj1 instanceof Date && obj2 instanceof Date) {
    return obj1.getTime() === obj2.getTime();
  }

  const keys1 = Object.keys(obj1);
  const keys2 = Object.keys(obj2);

  if (keys1.length !== keys2.length) return false;

  return keys1.every((key) => {
    return keys2.includes(key) && areObjectsEqual(obj1[key], obj2[key]);
  });
}
