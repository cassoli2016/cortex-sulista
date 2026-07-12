export interface BadgeProps {
  /** Estado operacional */
  tone?: 'success' | 'warning' | 'danger' | 'info' | 'neutral';
  /** Mostra o ponto de status */
  dot?: boolean;
  children?: React.ReactNode;
}
export declare function Badge(props: BadgeProps): JSX.Element;
