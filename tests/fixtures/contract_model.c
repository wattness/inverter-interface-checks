/* SPDX-License-Identifier: Apache-2.0 */
/* Independently written software fixture; no inverter equations or stepping. */
#define GFM_BATTERY_DLL_EXPORTS
#include "IEEE_Cigre_DLLInterface.h"
#include <math.h>
#include <signal.h>
#include <stddef.h>
#include <stdio.h>
#if !defined(_WIN32)
#include <sys/types.h>
#include <unistd.h>
#endif

#ifndef FIXTURE_MODE
#define FIXTURE_MODE 0
#endif

typedef struct {
    float alpha;
    double tau;
    int32_t count;
#if FIXTURE_MODE == 21 || FIXTURE_MODE == 22
    char flag;
#else
    uint8_t flag;
#endif
    const char *label;
} Parameters;

typedef struct { double samples[3]; uint8_t enable; } Inputs;
typedef struct { double value; } Outputs;

static IEEE_Cigre_DLLInterface_Signal inputs[] = {
    { "samples", "Software test vector", "", 9, 3 },
    { "enable", "Software test flag", "", 3, 1 },
};
static IEEE_Cigre_DLLInterface_Signal outputs[] = {
    { "value", "Unused software output", "", 9, 1 },
};
static IEEE_Cigre_DLLInterface_Parameter parameters[] = {
    { "alpha", "Software", "Float32 parameter", "", 8, 0,
      { .Real32_Val = 1.0f }, { .Real32_Val = -2.0f }, { .Real32_Val = 2.0f } },
    { "tau", "Software", "Float64 parameter", "", 9, 0,
      { .Real64_Val = 2.5 }, { .Real64_Val = 0.1 }, { .Real64_Val = 20.0 } },
    { "count", "Software", "Signed integer parameter", "", 6, 0,
      { .Int32_Val = 3 }, { .Int32_Val = 0 }, { .Int32_Val = 7 } },
#if FIXTURE_MODE == 21
    { "flag", "Software", "Signed char parameter", "", 1, 0,
      { .Char_Val = 1 }, { .Char_Val = -2 }, { .Char_Val = 2 } },
#elif FIXTURE_MODE == 22
    { "flag", "Software", "Unsigned char parameter", "", 1, 0,
      { .Char_Val = 1 }, { .Char_Val = 0 }, { .Char_Val = (char)255 } },
#else
    { "flag", "Software", "Unsigned integer parameter", "", 3, 0,
      { .Uint8_Val = 1 }, { .Uint8_Val = 0 }, { .Uint8_Val = 1 } },
#endif
    { "label", "Software", "String parameter", "", 10, 0,
      { .Char_Ptr = "software-fixture" }, { .Int32_Val = 0 }, { .Int32_Val = 0 } },
};
static IEEE_Cigre_DLLInterface_Model_Info info = {
    .DLLInterfaceVersion = { 1, 1, 0, 0 },
    .ModelName = "SoftwareContractFixture",
    .ModelVersion = "1.0",
    .ModelDescription = "Interface-checker software fixture",
    .GeneralInformation = "No electrical model",
    .ModelCreated = "", .ModelCreator = "Wattness",
    .ModelLastModifiedDate = "", .ModelLastModifiedBy = "",
    .ModelModifiedComment = "", .ModelModifiedHistory = "",
    .FixedStepBaseSampleTime = 0.001, .EMT_RMS_Mode = 1,
    .NumInputPorts = 2, .InputPortsInfo = inputs,
    .NumOutputPorts = 1, .OutputPortsInfo = outputs,
    .NumParameters = 5, .ParametersInfo = parameters,
    .NumIntStates = 2, .NumFloatStates = 1, .NumDoubleStates = 1,
};

const IEEE_Cigre_DLLInterface_Model_Info * MODEL_CALL Model_GetInfo(void) {
#if FIXTURE_MODE == 9
    parameters[0].DataType = 99;
#elif FIXTURE_MODE == 14
    return NULL;
#elif FIXTURE_MODE == 24
    info.NumParameters = 1;
    info.ParametersInfo = NULL;
#elif FIXTURE_MODE == 25
    info.FixedStepBaseSampleTime = NAN;
#elif FIXTURE_MODE == 26
    parameters[1].DefaultValue.Real64_Val = NAN;
#elif FIXTURE_MODE == 27
    inputs[0].Width = -1;
#elif FIXTURE_MODE == 28
    parameters[1].Name = "alpha";
#elif FIXTURE_MODE == 29
    info.DLLInterfaceVersion[0] = 2;
#elif FIXTURE_MODE == 30
    info.ModelName = "\xff";
#endif
    return &info;
}

int MODEL_CALL Model_CheckParameters(IEEE_Cigre_DLLInterface_Instance *instance) {
    Parameters *p;
    int invalid;
    if (!instance) return 2;
#if FIXTURE_MODE != 8
    instance->LastErrorMessage = NULL;
#endif
    instance->LastGeneralMessage = NULL;
    if (!instance->Parameters) return 2;
    p = (Parameters *)instance->Parameters;
#if FIXTURE_MODE == 11
    raise(SIGABRT);
#elif FIXTURE_MODE == 12
    { volatile unsigned long counter = 0; for (;;) ++counter; }
#elif FIXTURE_MODE == 16
    for (;;) puts("deliberate software-fixture output overflow");
#elif FIXTURE_MODE == 23 && !defined(_WIN32)
    {
        pid_t child = fork();
        if (child == 0) for (;;) pause();
        fprintf(stderr, "descendant_pid:%ld\n", (long)child);
    }
#elif FIXTURE_MODE == 31
    { int i; for (i = 0; i < 6000; ++i) puts("deliberate fast software-fixture output overflow"); }
#endif
    invalid = p->alpha < -2.0f || p->alpha > 2.0f
        || p->tau < 0.1 || p->tau > 20.0
        || p->count < 0 || p->count > 7;
#if FIXTURE_MODE == 21
    invalid = invalid || p->flag < -2 || p->flag > 2;
#elif FIXTURE_MODE != 22
    invalid = invalid || p->flag > 1;
#endif
#if FIXTURE_MODE != 1
    invalid = invalid || !isfinite(p->alpha) || !isfinite(p->tau);
#endif
#if FIXTURE_MODE == 2
    invalid = invalid || p->alpha == -2.0f || p->alpha == 2.0f;
#elif FIXTURE_MODE == 5
    p->count = 0;
#elif FIXTURE_MODE == 6
    ((Inputs *)instance->ExternalInputs)->samples[0] = 1.0;
#elif FIXTURE_MODE == 7
    ((unsigned char *)p)[sizeof(*p)] ^= 1;
#elif FIXTURE_MODE == 13
    parameters[1].DefaultValue.Real64_Val = 3.5;
#elif FIXTURE_MODE == 17
    instance->IntStates[0] += 1;
#elif FIXTURE_MODE == 18
    ((char *)p->label)[0] = 'X';
#elif FIXTURE_MODE == 19
    ((unsigned char *)instance->FloatStates)[sizeof(float)] ^= 1;
#elif FIXTURE_MODE == 20
    ((unsigned char *)instance)[offsetof(IEEE_Cigre_DLLInterface_Instance, SimTool_EMT_RMS_Mode) + 1] ^= 1;
#endif
    if (invalid) {
#if FIXTURE_MODE != 4
        instance->LastErrorMessage = "Software parameter rejected";
#endif
        return 2;
    }
#if FIXTURE_MODE == 3
    return 7;
#else
    return 0;
#endif
}

int MODEL_CALL Model_FirstCall(IEEE_Cigre_DLLInterface_Instance *instance) { (void)instance; return 0; }
int MODEL_CALL Model_PrintInfo(void) { return 0; }
int MODEL_CALL Model_Initialize(IEEE_Cigre_DLLInterface_Instance *instance) { (void)instance; return 0; }
int MODEL_CALL Model_Outputs(IEEE_Cigre_DLLInterface_Instance *instance) { (void)instance; return 0; }
int MODEL_CALL Model_Iterate(IEEE_Cigre_DLLInterface_Instance *instance) { (void)instance; return 0; }
#if FIXTURE_MODE != 10
int MODEL_CALL Model_Terminate(IEEE_Cigre_DLLInterface_Instance *instance) { (void)instance; return 0; }
#endif

#ifdef PRINT_LAYOUT
int main(void) {
    printf("{\"Signal\":%zu,\"Parameter\":%zu,\"ModelInfo\":%zu,\"Instance\":%zu,"
           "\"Parameters\":%zu,\"parameters_offsets\":[%zu,%zu,%zu,%zu,%zu]}\n",
           sizeof(IEEE_Cigre_DLLInterface_Signal), sizeof(IEEE_Cigre_DLLInterface_Parameter),
           sizeof(IEEE_Cigre_DLLInterface_Model_Info), sizeof(IEEE_Cigre_DLLInterface_Instance),
           sizeof(Parameters), offsetof(Parameters, alpha), offsetof(Parameters, tau),
           offsetof(Parameters, count), offsetof(Parameters, flag), offsetof(Parameters, label));
    return 0;
}
#endif
