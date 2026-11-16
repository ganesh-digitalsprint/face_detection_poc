export const blankBranch = { name: '', code: '', status: 'active', address: '', pincode: '', timezone: 'Asia/Kolkata', manager: '', phone: '', email: '' };
export const branchFields = Object.keys(blankBranch);
export const timezones = [...new Set(['Asia/Kolkata', 'UTC', ...(Intl.supportedValuesOf?.('timeZone') || [])])];

export function validateBranch(form, cityId) {
  const errors = {};
  if (!cityId) errors.city = 'Choose a zone and city.';
  if (form.name.trim().length < 2 || form.name.trim().length > 120) errors.name = 'Enter a branch name (2–120 characters).';
  if (!/^[A-Za-z][A-Za-z0-9-]{2,38}$/.test(form.code)) errors.code = 'Use 3–39 letters, digits or dashes, starting with a letter.';
  if (form.pincode && !/^\d{6}$/.test(form.pincode)) errors.pincode = 'Pincode must be 6 digits.';
  if (form.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) errors.email = 'Enter a valid email address.';
  if (form.phone && !/^\+?[0-9\s()-]{8,20}$/.test(form.phone)) errors.phone = 'Enter a valid phone number.';
  if (!timezones.includes(form.timezone)) errors.timezone = 'Choose a valid IANA time zone.';
  return errors;
}
