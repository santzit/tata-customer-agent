import InboxHelpCenterClient from './InboxHelpCenterClient';

export const generateStaticParams = async (): Promise<Array<{ id: string; inboxId: string }>> => [
  { id: 'placeholder', inboxId: 'placeholder' },
];

export default function InboxHelpCenterPage() {
  return <InboxHelpCenterClient />;
}
