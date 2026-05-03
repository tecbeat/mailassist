export interface ExtractedOtpCodeResponse {
  id: string;
  mail_account_id: string;
  mail_uid: string;
  sender_email: string | null;
  mail_subject: string | null;
  code: string;
  service: string | null;
  code_type: string;
  expires_at: string | null;
  is_expired: boolean;
  created_at: string;
  updated_at: string;
}

export interface ExtractedOtpCodeListResponse {
  items: ExtractedOtpCodeResponse[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

export type ListOtpCodesApiOtpCodesGetSort = "newest" | "oldest" | "service" | "expiry";

export interface ListOtpCodesApiOtpCodesGetParams {
  page?: number;
  per_page?: number;
  service?: string;
  code_type?: string;
  active_only?: boolean;
  sort?: ListOtpCodesApiOtpCodesGetSort;
}
