// The backend has no "get employee" endpoint, so names of employees registered from this
// browser are remembered locally for display only. Never used for any access decision.
const KEY = 'face-ai-poc.employees';

const readAll = () => {
  try {
    return JSON.parse(localStorage.getItem(KEY)) ?? {};
  } catch {
    return {};
  }
};

export const rememberEmployee = (employee) => {
  try {
    localStorage.setItem(KEY, JSON.stringify({ ...readAll(), [employee.employee_id]: employee }));
  } catch {
    /* storage unavailable: display falls back to the employee ID */
  }
};

export const findEmployee = (employeeId) => readAll()[employeeId] ?? null;
