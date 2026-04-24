import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

interface ListSkeletonProps {
  /** Number of skeleton cards to render (default: 5). */
  count?: number;
  /** Tailwind width classes for each skeleton line inside the card. */
  lines?: string[];
}

/**
 * Generic list skeleton loader.
 *
 * Renders `count` cards, each with a header row (title + badge) and
 * additional body lines whose widths can be customised via `lines`.
 */
export function ListSkeleton({
  count = 5,
  lines = ["w-1/2", "w-2/3"],
}: ListSkeletonProps) {
  return (
    <div className="space-y-3">
      {Array.from({ length: count }).map((_, i) => (
        <Card key={i}>
          <CardContent className="space-y-2 pt-4">
            <div className="flex items-center justify-between">
              <Skeleton className="h-4 w-1/3" />
              <Skeleton className="h-5 w-16" />
            </div>
            {lines.map((w, j) => (
              <Skeleton key={j} className={`h-3 ${w}`} />
            ))}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
