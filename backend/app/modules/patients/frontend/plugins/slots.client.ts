import { defineAsyncComponent } from 'vue'
import { registerSlot } from '~~/app/composables/useModuleSlots'

export default defineNuxtPlugin(() => {
  registerSlot('dashboard.activity', {
    id: 'patients.dashboard.recent',
    component: defineAsyncComponent(() => import('../components/home/RecentPatientsPanel.vue')),
    order: 10,
    permission: 'patients.read'
  })

  // QuickActionsCard — patients-owned card. Renders last in the grid
  // (order 60) so the data snapshots from other modules surface first.
  registerSlot('patient.summary.cards', {
    id: 'patients.patient.summary.cards.quickActions',
    component: defineAsyncComponent(() => import('../components/patient/QuickActionsCard.vue')),
    order: 60,
    permission: 'patients.read'
  })
})
