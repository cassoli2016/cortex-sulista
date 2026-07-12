export interface SelectProps {
  label?: string;
  /** Strings ou {value,label} */
  options?: Array<string | { value: string; label: string }>;
  hint?: string;
  error?: string;
  value?: string;
  onChange?: (e: any) => void;
  disabled?: boolean;
}
export declare function Select(props: SelectProps): JSX.Element;
