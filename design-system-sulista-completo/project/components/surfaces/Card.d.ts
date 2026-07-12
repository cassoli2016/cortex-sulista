export interface CardProps {
  /** Rótulo uppercase acima do título */
  kicker?: string;
  title?: React.ReactNode;
  children?: React.ReactNode;
  /** Rodapé separado por borda */
  footer?: React.ReactNode;
  /** Eleva a sombra no hover */
  hoverable?: boolean;
  padding?: number | string;
}
export declare function Card(props: CardProps): JSX.Element;
