import { useTranslation } from 'react-i18next'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'

interface Props {
  open: boolean
  count: number
  kind: 'category' | 'type'
  loading?: boolean
  onConfirm: () => void
  onClose: () => void
}

/**
 * Post-edit confirmation: after a transaction's category or type changes,
 * offer to apply the same change to every other transaction with the same
 * description, showing how many would be affected.
 */
export function ApplyToSimilarDialog({ open, count, kind, loading, onConfirm, onClose }: Props) {
  const { t } = useTranslation()
  const bodyKey =
    kind === 'category'
      ? 'transactions.applySimilarCategoryBody'
      : 'transactions.applySimilarTypeBody'
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('transactions.applySimilarTitle')}</DialogTitle>
        </DialogHeader>
        <p className="text-sm text-muted-foreground">{t(bodyKey, { count })}</p>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={loading}>
            {t('transactions.applySimilarSkip')}
          </Button>
          <Button onClick={onConfirm} disabled={loading}>
            {loading ? t('common.loading') : t('transactions.applySimilarConfirm', { count })}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
