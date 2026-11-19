import Badge from '../../components/Badge'
import Card from '../../components/Card'
import InfoList from '../../components/InfoList'
import { STATUS_LABELS, STATUS_VARIANTS, createdDate } from './accountFormat'

// The details panel for the selected engineer (ADM-02). The account actions
// are added here by their own stories: ADM-03 (activate or deactivate),
// ADM-05 (change password) and ADM-04 (delete).

function EngineerDetails({ engineer }) {
  return (
    <Card title={engineer.name} className="admin-panel">
      <InfoList
        items={[
          { label: 'Email', value: engineer.email },
          {
            label: 'Status',
            value: (
              <Badge variant={STATUS_VARIANTS[engineer.status]}>
                {STATUS_LABELS[engineer.status]}
              </Badge>
            ),
          },
          { label: 'Created', value: createdDate(engineer.created_at) },
        ]}
      />
      <p className="admin-panel-note">Account actions will appear here.</p>
    </Card>
  )
}

export default EngineerDetails
