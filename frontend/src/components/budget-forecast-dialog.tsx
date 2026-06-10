import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useMutation } from '@tanstack/react-query'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { DatePickerInput } from '@/components/ui/date-picker-input'
import { budgets as budgetsApi } from '@/lib/api'
import { toast } from 'sonner'

interface Props {
  open: boolean
  targetMonth: string // YYYY-MM-DD of the month selected on the page
  onClose: () => void
  onApplied: () => void
}

type Row = {
  category_id: string
  category_name: string
  suggested_amount: number
  selected: boolean
  amount: string
}

/**
 * Analyze expenses over a chosen period and turn them into budgets for the
 * page's currently selected month. The user can edit the suggested amounts
 * and deselect categories before applying.
 */
export function BudgetForecastDialog({ open, targetMonth, onClose, onApplied }: Props) {
  const { t } = useTranslation()
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [strategy, setStrategy] = useState<'average' | 'total'>('average')
  const [rows, setRows] = useState<Row[]>([])

  const analyze = useMutation({
    mutationFn: () => budgetsApi.forecast(from, to, strategy),
    onSuccess: (data) =>
      setRows(
        data.items.map((i) => ({
          category_id: i.category_id,
          category_name: i.category_name,
          suggested_amount: i.suggested_amount,
          selected: true,
          amount: String(i.suggested_amount),
        })),
      ),
    onError: () => toast.error(t('budgets.forecastError')),
  })

  const apply = useMutation({
    mutationFn: () =>
      budgetsApi.applyForecast({
        month: targetMonth,
        is_recurring: false,
        items: rows
          .filter((r) => r.selected)
          .map((r) => ({ category_id: r.category_id, amount: Number(r.amount) })),
      }),
    onSuccess: (res) => {
      toast.success(t('budgets.forecastApplied', { count: res.created + res.updated }))
      onApplied()
      onClose()
    },
    onError: () => toast.error(t('budgets.forecastError')),
  })

  const selectedCount = rows.filter((r) => r.selected).length

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('budgets.forecastTitle')}</DialogTitle>
        </DialogHeader>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <div className="space-y-1">
            <Label>{t('budgets.periodFrom')}</Label>
            <DatePickerInput value={from} onChange={setFrom} />
          </div>
          <div className="space-y-1">
            <Label>{t('budgets.periodTo')}</Label>
            <DatePickerInput value={to} onChange={setTo} />
          </div>
          <div className="space-y-1">
            <Label>{t('budgets.strategy')}</Label>
            <select
              className="w-full border border-border rounded-md px-3 py-2 text-sm bg-background h-9"
              value={strategy}
              onChange={(e) => setStrategy(e.target.value as 'average' | 'total')}
            >
              <option value="average">{t('budgets.strategyAverage')}</option>
              <option value="total">{t('budgets.strategyTotal')}</option>
            </select>
          </div>
        </div>

        <Button
          type="button"
          variant="outline"
          disabled={!from || !to || analyze.isPending}
          onClick={() => analyze.mutate()}
        >
          {analyze.isPending ? t('common.loading') : t('budgets.analyze')}
        </Button>

        {analyze.isSuccess && rows.length === 0 && (
          <p className="text-sm text-muted-foreground">{t('budgets.forecastEmpty')}</p>
        )}

        {rows.length > 0 && (
          <div className="max-h-72 overflow-y-auto border rounded-md divide-y">
            {rows.map((r, idx) => (
              <div key={r.category_id} className="flex items-center gap-3 px-3 py-2">
                <input
                  type="checkbox"
                  checked={r.selected}
                  onChange={(e) =>
                    setRows((rs) => rs.map((x, i) => (i === idx ? { ...x, selected: e.target.checked } : x)))
                  }
                />
                <span className="flex-1 text-sm">{r.category_name}</span>
                <Input
                  type="number"
                  step="0.01"
                  className="w-28"
                  value={r.amount}
                  onChange={(e) =>
                    setRows((rs) => rs.map((x, i) => (i === idx ? { ...x, amount: e.target.value } : x)))
                  }
                />
              </div>
            ))}
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button disabled={selectedCount === 0 || apply.isPending} onClick={() => apply.mutate()}>
            {apply.isPending ? t('common.loading') : t('budgets.createBudgets')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
