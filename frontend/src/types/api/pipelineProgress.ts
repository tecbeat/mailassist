/**
 * Live pipeline progress for a processing email (from Valkey).
 */

export interface PipelinePluginName {
  name: string;
  display_name: string;
}

export interface PipelineProgress {
  phase?: string | null;
  current_plugin?: string | null;
  current_plugin_display?: string | null;
  plugin_index?: number | null;
  plugins_total?: number | null;
  plugin_names?: PipelinePluginName[] | null;
}
