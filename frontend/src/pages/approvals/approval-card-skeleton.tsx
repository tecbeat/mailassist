import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent } from "@/components/ui/card";

export function ApprovalCardSkeleton() {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-start gap-4">
          <Skeleton className="mt-1 h-4 w-4 rounded-sm" />
          <div className="min-w-0 flex-1 space-y-3">
            <div className="space-y-1.5">
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-3 w-1/3" />
            </div>
            <div className="flex gap-2">
              <Skeleton className="h-5 w-20 rounded-md" />
              <Skeleton className="h-5 w-40 rounded-md" />
            </div>
            <Skeleton className="h-3 w-2/3" />
          </div>
          <div className="flex shrink-0 gap-2">
            <Skeleton className="h-8 w-8 rounded-md" />
            <Skeleton className="h-8 w-8 rounded-md" />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
