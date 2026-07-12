export interface TooltipProps {
  /** Texto do tooltip */
  content: React.ReactNode;
  side?: 'top' | 'bottom';
  /** Elemento alvo */
  children?: React.ReactNode;
}
export declare function Tooltip(props: TooltipProps): JSX.Element;
