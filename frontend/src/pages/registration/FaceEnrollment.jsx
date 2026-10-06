import { useState } from 'react';
import { CheckCircle2, UserPlus } from 'lucide-react';
import { Link, useParams } from 'react-router-dom';
import Card from '../../components/common/Card.jsx';
import EmployeeSummary from '../../components/registration/EmployeeSummary.jsx';
import FaceEnrollmentForm from '../../components/registration/FaceEnrollmentForm.jsx';
import RegistrationProgress from '../../components/registration/RegistrationProgress.jsx';
import { findEmployee } from '../../utils/employeeDirectory.js';

const DONE = ['Employee registered', 'Authorization registered', 'Face enrollment completed'];

export default function FaceEnrollment() {
  const { employeeId } = useParams();
  const [result, setResult] = useState(null);
  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <RegistrationProgress current={result ? 4 : 2} />
      <EmployeeSummary employeeId={employeeId} employee={findEmployee(employeeId)} />
      <FaceEnrollmentForm employeeId={employeeId} onEnrolled={setResult} />
      {result && (
        <Card title="Registration Complete">
          <ul className="space-y-1 text-sm font-medium text-emerald-700" role="status">
            {DONE.map((text) => (
              <li key={text} className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4" aria-hidden />{text}</li>
            ))}
          </ul>
          <Link to="/registration/employees" className="mt-4 inline-flex items-center gap-2 text-sm font-medium text-brand hover:underline">
            <UserPlus className="h-4 w-4" aria-hidden /> Register another employee
          </Link>
        </Card>
      )}
    </div>
  );
}
