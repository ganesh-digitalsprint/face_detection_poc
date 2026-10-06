import { findEmployee } from '../../utils/employeeDirectory.js';
import StageRow from './StageRow.jsx';

/** Identity checklist row(s). Name is display-only, looked up locally from the employee ID. */
export default function IdentityStatus({ liveness, recognition }) {
  if (recognition?.matched) {
    const name = findEmployee(recognition.employee_id)?.name;
    return (
      <>
        <StageRow tone="pass" label="Identity verified" />
        <StageRow tone="pass" label={`Employee: ${name ?? recognition.employee_id}`} detail={name ? `Employee ID: ${recognition.employee_id}` : undefined} />
      </>
    );
  }
  if (recognition) return <StageRow tone="fail" label="Identity not recognized" />;
  if (liveness?.passed) return <StageRow tone="pending" label="Identity verification" />;
  return <StageRow tone="idle" label="Identity verification" />;
}
