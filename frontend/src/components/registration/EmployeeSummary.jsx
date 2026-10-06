import Card from '../common/Card.jsx';

/** `employee` may be null when the employee was registered elsewhere (only the ID is known). */
export default function EmployeeSummary({ employeeId, employee }) {
  const rows = [
    ['Employee ID', employeeId],
    ['Name', employee?.name],
    ['Department', employee?.department],
    ['Designation', employee?.designation],
  ];
  return (
    <Card title="Employee">
      <dl className="grid grid-cols-[8rem_1fr] gap-y-1 text-sm">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-slate-500">{label}</dt>
            <dd className="text-slate-800">{value || '—'}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}
