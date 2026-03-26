import AccountInboxesClient from './AccountInboxesClient';

export const generateStaticParams = async (): Promise<Array<{ id: string }>> => [
  { id: 'placeholder' },
];

export default function AccountInboxesPage() {
  return <AccountInboxesClient />;
}
