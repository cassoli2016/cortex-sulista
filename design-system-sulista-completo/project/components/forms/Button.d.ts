/**
 * @startingPoint section="Componentes" subtitle="Ação primária, secundária, outline, ghost e danger" viewport="700x260"
 */
export interface ButtonProps {
  /** Variante visual */
  variant?: 'primary' | 'secondary' | 'outline' | 'ghost' | 'danger';
  size?: 'sm' | 'md' | 'lg';
  disabled?: boolean;
  /** Ocupa toda a largura */
  block?: boolean;
  children?: React.ReactNode;
  onClick?: () => void;
}
export declare function Button(props: ButtonProps): JSX.Element;
