<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import type { DentalKnowledgeReviewRecord, DentalKnowledgeReviewStatus } from '../../../composables/useDentalKnowledgeReview'
import { PERMISSIONS } from '~~/app/config/permissions'

definePageMeta({ middleware: ['auth'] })

const api = useDentalKnowledgeReview()
const { can } = usePermissions()

if (!can(PERMISSIONS.patientAgent.knowledgeRead)) {
  await navigateTo('/')
}

const canReview = computed(() => can(PERMISSIONS.patientAgent.knowledgeReview))
const status = ref<DentalKnowledgeReviewStatus | 'all'>('in_review')
const items = ref<DentalKnowledgeReviewRecord[]>([])
const selected = ref<DentalKnowledgeReviewRecord | null>(null)
const note = ref('')
const isLoading = ref(false)
const isSaving = ref(false)
const errorMessage = ref<string | null>(null)

const statusOptions = [
  { label: 'In review', value: 'in_review' },
  { label: 'Draft', value: 'draft' },
  { label: 'Approved', value: 'approved' },
  { label: 'Rejected', value: 'rejected' },
  { label: 'All', value: 'all' }
]

async function load() {
  isLoading.value = true
  errorMessage.value = null
  try {
    const response = await api.list(status.value === 'all' ? undefined : status.value)
    items.value = response.data
    if (selected.value) {
      selected.value = items.value.find(item => item.id === selected.value?.id) ?? null
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Unable to load dental knowledge.'
  } finally {
    isLoading.value = false
  }
}

async function selectItem(item: DentalKnowledgeReviewRecord) {
  errorMessage.value = null
  try {
    selected.value = (await api.get(item.id)).data
    note.value = selected.value.decision_note ?? ''
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Unable to open this knowledge record.'
  }
}

async function runTransition(action: 'submit' | 'approve' | 'reject') {
  if (!selected.value || !canReview.value || isSaving.value) return
  if (action === 'reject' && !note.value.trim()) {
    errorMessage.value = 'A rejection reason is required.'
    return
  }
  isSaving.value = true
  errorMessage.value = null
  try {
    const id = selected.value.id
    const response = action === 'submit'
      ? await api.submit(id)
      : action === 'approve'
        ? await api.approve(id, note.value)
        : await api.reject(id, note.value)
    selected.value = response.data
    note.value = response.data.decision_note ?? ''
    await load()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Unable to update review status.'
  } finally {
    isSaving.value = false
  }
}

function formatDate(value?: string | null) {
  if (!value) return '—'
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

onMounted(load)
</script>

<template>
  <div class="container mx-auto p-4 space-y-4">
    <header class="flex items-center justify-between gap-3 flex-wrap">
      <div>
        <h1 class="text-h1">Dental knowledge review</h1>
        <p class="text-sm text-muted mt-1">Review curated patient-education content before it is eligible for the patient AI.</p>
      </div>
      <USelectMenu
        v-model="status"
        :items="statusOptions"
        value-key="value"
        label-key="label"
        class="w-44"
        @update:model-value="load"
      />
    </header>

    <UAlert v-if="errorMessage" color="error" variant="soft" :description="errorMessage" />

    <div class="grid lg:grid-cols-[minmax(18rem,24rem)_1fr] gap-4">
      <UCard>
        <template #header>
          <div class="flex items-center justify-between">
            <span class="font-semibold">Knowledge records</span>
            <UBadge variant="soft">{{ items.length }}</UBadge>
          </div>
        </template>

        <div v-if="isLoading" class="py-8 text-center text-muted">Loading…</div>
        <div v-else-if="!items.length" class="py-8 text-center text-muted">No records match this filter.</div>
        <div v-else class="space-y-2">
          <button
            v-for="item in items"
            :key="item.id"
            type="button"
            class="w-full text-left rounded-lg border p-3 hover:bg-elevated transition"
            :class="selected?.id === item.id ? 'ring-2 ring-primary' : ''"
            @click="selectItem(item)"
          >
            <div class="flex items-start justify-between gap-2">
              <span class="font-medium">{{ item.title }}</span>
              <UBadge variant="soft">{{ item.review_status.replace('_', ' ') }}</UBadge>
            </div>
            <div class="mt-2 text-xs text-muted">{{ item.topic }} · {{ item.locale }} · v{{ item.version }}</div>
            <div class="mt-1 text-xs text-muted">{{ item.source_name }}</div>
          </button>
        </div>
      </UCard>

      <UCard v-if="selected">
        <template #header>
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 class="text-xl font-semibold">{{ selected.title }}</h2>
              <div class="text-sm text-muted mt-1">{{ selected.entry_key }} · v{{ selected.version }} · {{ selected.locale }}</div>
            </div>
            <UBadge variant="soft">{{ selected.review_status.replace('_', ' ') }}</UBadge>
          </div>
        </template>

        <div class="space-y-5">
          <section>
            <h3 class="font-semibold mb-2">Reviewable content</h3>
            <div class="whitespace-pre-wrap rounded-lg border bg-elevated p-4 text-sm leading-6">{{ selected.content }}</div>
          </section>

          <section class="grid sm:grid-cols-2 gap-3 text-sm">
            <div><span class="font-medium">Topic:</span> {{ selected.topic }}</div>
            <div><span class="font-medium">Source:</span> {{ selected.source_name }}</div>
            <div class="sm:col-span-2 break-all"><span class="font-medium">Source reference:</span> {{ selected.source_reference }}</div>
            <div><span class="font-medium">Submitted:</span> {{ formatDate(selected.submitted_at) }}</div>
            <div><span class="font-medium">Reviewed:</span> {{ formatDate(selected.reviewed_at) }}</div>
          </section>

          <UFormField label="Decision note">
            <UTextarea v-model="note" :disabled="!canReview" :rows="4" maxlength="4000" placeholder="Optional for approval; required for rejection." />
          </UFormField>

          <UAlert
            v-if="!canReview"
            color="neutral"
            variant="soft"
            description="You have read access only. Dentist/admin review permission is required to change status."
          />

          <div v-if="canReview" class="flex flex-wrap gap-2">
            <UButton
              v-if="selected.review_status === 'draft' || selected.review_status === 'rejected'"
              :loading="isSaving"
              @click="runTransition('submit')"
            >Submit for review</UButton>
            <template v-if="selected.review_status === 'in_review'">
              <UButton color="success" :loading="isSaving" @click="runTransition('approve')">Approve for patient education</UButton>
              <UButton color="error" variant="soft" :loading="isSaving" @click="runTransition('reject')">Reject</UButton>
            </template>
          </div>
        </div>
      </UCard>

      <UCard v-else>
        <div class="py-16 text-center text-muted">Select a knowledge record to review its content and provenance.</div>
      </UCard>
    </div>
  </div>
</template>
