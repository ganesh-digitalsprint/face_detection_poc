/** Only a selected canonical branch carries attribution into a Branch session. */
export function canonicalBranchId(scope) {
  return scope?.type === 'branch' && typeof scope.id === 'string' && scope.id ? scope.id : null;
}

export function branchIdQuery(scope) {
  const id = canonicalBranchId(scope);
  return id ? { branch_id: id } : {};
}

export function branchIdBody(scope) {
  return branchIdQuery(scope);
}
