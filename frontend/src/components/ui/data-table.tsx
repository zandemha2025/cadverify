"use client";

import * as React from "react";
import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import { TableSkeleton } from "@/components/ui/skeleton";

export interface DataTableProps<TData, TValue> {
  columns: ColumnDef<TData, TValue>[];
  data: TData[];
  density?: "compact" | "comfortable";
  onRowClick?: (row: TData) => void;
  emptyState?: React.ReactNode;
  loading?: boolean;
}

/**
 * TanStack-backed table skin. Used by History, Batch list/items, Keys.
 * Sortable headers; numeric columns right-align mono via meta.numeric.
 */
export function DataTable<TData, TValue>({
  columns,
  data,
  density = "comfortable",
  onRowClick,
  emptyState,
  loading,
}: DataTableProps<TData, TValue>) {
  const [sorting, setSorting] = React.useState<SortingState>([]);

  const table = useReactTable({
    data,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  const rowH = density === "compact" ? "h-9" : "h-11";

  if (loading) {
    return <TableSkeleton rows={6} cols={columns.length || 4} />;
  }

  if (data.length === 0 && emptyState) {
    return <>{emptyState}</>;
  }

  return (
    <div className="overflow-hidden rounded-[var(--radius)] border border-border bg-card">
      <Table>
        <TableHeader>
          {table.getHeaderGroups().map((hg) => (
            <TableRow key={hg.id} className="hover:bg-transparent">
              {hg.headers.map((header) => {
                const numeric = (header.column.columnDef.meta as
                  | { numeric?: boolean }
                  | undefined)?.numeric;
                const canSort = header.column.getCanSort();
                const sorted = header.column.getIsSorted();
                return (
                  <TableHead key={header.id} numeric={numeric}>
                    {header.isPlaceholder ? null : canSort ? (
                      <button
                        type="button"
                        onClick={header.column.getToggleSortingHandler()}
                        className={cn(
                          "inline-flex items-center gap-1 hover:text-foreground",
                          numeric && "flex-row-reverse"
                        )}
                      >
                        {flexRender(
                          header.column.columnDef.header,
                          header.getContext()
                        )}
                        {sorted === "asc" ? (
                          <ArrowUp className="size-3" />
                        ) : sorted === "desc" ? (
                          <ArrowDown className="size-3" />
                        ) : (
                          <ChevronsUpDown className="size-3 opacity-50" />
                        )}
                      </button>
                    ) : (
                      flexRender(
                        header.column.columnDef.header,
                        header.getContext()
                      )
                    )}
                  </TableHead>
                );
              })}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {table.getRowModel().rows.map((row) => (
            <TableRow
              key={row.id}
              className={cn(rowH, onRowClick && "cursor-pointer")}
              onClick={onRowClick ? () => onRowClick(row.original) : undefined}
            >
              {row.getVisibleCells().map((cell) => {
                const numeric = (cell.column.columnDef.meta as
                  | { numeric?: boolean }
                  | undefined)?.numeric;
                return (
                  <TableCell key={cell.id} numeric={numeric}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </TableCell>
                );
              })}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
