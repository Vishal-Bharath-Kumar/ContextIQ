import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { WizardStepper } from "../../components/wizard/WizardStepper";
import { StepTypeSelection } from "../../components/wizard/steps/StepTypeSelection";
import { StepCredentials } from "../../components/wizard/steps/StepCredentials";
import { StepScope } from "../../components/wizard/steps/StepScope";
import { StepSchedule } from "../../components/wizard/steps/StepSchedule";
import { useCreateConnector } from "../../services/connectorService";
import type {
  ConnectorCreatePayload,
  CredentialFields,
  ScheduleFields,
  ScopeFields,
  TypeFields,
} from "../../schemas/connectorWizard";
import { GlassCard } from "../../components/ui/GlassCard";
import { PageHeader } from "../../components/ui/PageHeader";

const STEPS = ["Type", "Credentials", "Scope", "Schedule"];

export function AddConnectorPage() {
  const navigate = useNavigate();
  const { mutateAsync, isPending } = useCreateConnector();
  const [currentStep, setCurrentStep] = useState(0);
  const [wizardData, setWizardData] = useState<Partial<ConnectorCreatePayload>>({});
  const [submitError, setSubmitError] = useState<string | null>(null);

  function handleTypeNext(data: TypeFields) {
    setWizardData((prev) => ({ ...prev, ...data }));
    setCurrentStep(1);
  }

  function handleCredentialsNext(data: CredentialFields) {
    setWizardData((prev) => ({ ...prev, ...data }));
    setCurrentStep(2);
  }

  function handleScopeNext(data: ScopeFields) {
    setWizardData((prev) => ({ ...prev, ...data }));
    setCurrentStep(3);
  }

  async function handleScheduleNext(data: ScheduleFields) {
    setSubmitError(null);
    const payload = { ...wizardData, ...data } as ConnectorCreatePayload;
    try {
      await mutateAsync(payload);
      navigate("/connectors");
    } catch {
      setSubmitError("Failed to create connector. Please review the details and try again.");
    }
  }

  return (
    <main aria-labelledby="add-connector-heading" className="page-layout max-w-2xl">
      <PageHeader headingId="add-connector-heading" title="Add Connector" />

      <GlassCard className="p-6" delay={40}>
        <WizardStepper steps={STEPS} currentStep={currentStep} />

        {submitError && (
          <p role="alert" className="mb-4 text-sm text-red-600">
            {submitError}
          </p>
        )}

        {currentStep === 0 && (
          <StepTypeSelection defaults={wizardData} onNext={handleTypeNext} />
        )}
        {currentStep === 1 && (
          <StepCredentials
            connectorType={wizardData.connector_type ?? ""}
            defaults={wizardData}
            onNext={handleCredentialsNext}
            onBack={() => setCurrentStep(0)}
          />
        )}
        {currentStep === 2 && (
          <StepScope
            connectorType={wizardData.connector_type ?? ""}
            defaults={wizardData}
            onNext={handleScopeNext}
            onBack={() => setCurrentStep(1)}
          />
        )}
        {currentStep === 3 && (
          <StepSchedule
            defaults={wizardData}
            isPending={isPending}
            onNext={handleScheduleNext}
            onBack={() => setCurrentStep(2)}
          />
        )}
      </GlassCard>
    </main>
  );
}
