import type { PlannedTreatmentItem, TreatmentCatalogItem } from './index'

declare global {
  function useTreatmentPlans(): {
    fetchPatientPendingItems(patientId: string): Promise<PlannedTreatmentItem[]>
  }

  function useCatalog(): {
    searchItems(query: string, limit?: number): Promise<TreatmentCatalogItem[]>
    getItemName(item: TreatmentCatalogItem, locale?: string): string
    formatPrice(value: number | string | null | undefined): string
  }
}

export {}
