<script lang="ts">
  import FilterPanel from '$components/admin/FilterPanel.svelte';

  interface Props {
    open?: boolean;
    hasActiveFilters?: boolean;
    activeFilterCount?: number;
    onClear?: () => void;
    onApply?: () => void;
    onToggle?: () => void;
    title?: string;
    showToggleButton?: boolean;
  }

  let {
    open = $bindable(false),
    hasActiveFilters = false,
    activeFilterCount = 0,
    onClear,
    onApply,
    onToggle,
    title,
    showToggleButton,
  }: Props = $props();
</script>

<FilterPanel bind:open {hasActiveFilters} {activeFilterCount} {onClear} {onApply} {onToggle} {title} {showToggleButton}>
  <div data-testid="filter-content">Filter slot</div>
</FilterPanel>
