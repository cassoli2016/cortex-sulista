export interface TabsProps {
  /** Rótulos das abas */
  tabs: string[];
  /** Índice controlado */
  active?: number;
  defaultActive?: number;
  onChange?: (index: number) => void;
}
export declare function Tabs(props: TabsProps): JSX.Element;
