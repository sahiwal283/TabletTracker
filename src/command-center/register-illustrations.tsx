import * as React from "react";
import { DPP115BlisterMachine } from "../components/command-center/machine-illustrations/DPP115BlisterMachine";
import { HeatPressMachine } from "../components/command-center/machine-illustrations/HeatPressMachine";
import { StickeringMachine } from "../components/command-center/machine-illustrations/StickeringMachine";
import { BottleSealingMachine } from "../components/command-center/machine-illustrations/BottleSealingMachine";
import { PackagingStation } from "../components/command-center/machine-illustrations/PackagingStation";

(globalThis as unknown as { MesMachineIllustrations: Record<string, React.FC<{ running: boolean } & Record<string, unknown>>> })
  .MesMachineIllustrations = {
  DPP115BlisterMachine,
  HeatPressMachine,
  StickeringMachine,
  BottleSealingMachine,
  PackagingStation,
};
